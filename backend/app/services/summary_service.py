"""
backend/app/services/summary_service.py
==========================================
Aggregate and summary query logic.

All functions return Pydantic schema objects ready for the API layer.
No HTTP concerns here — routes handle 404s and response codes.

Public functions:
  get_system_summary   — overall database statistics (counts, year range)
  get_trend            — time-series for one indicator + county
  get_comparison       — cross-county comparison for one indicator + year
  get_indicator_stats  — min / max / avg value for an indicator
  get_available_years  — distinct years available for an indicator + county
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Dataset, Indicator, County, Observation
from app.schemas.summary import (
    SystemSummary,
    DatasetSummaryItem,
    TrendSummary,
    TrendPoint,
    ComparisonSummary,
    ComparisonItem,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _base_query(db: Session):
    """
    Base four-table join returning human-readable column names.

    Defined here (separately from observation_service) so this module has
    no cross-service import dependency.  The join logic is identical.
    """
    return (
        db.query(
            Observation.id,
            Dataset.name.label("dataset_name"),
            Indicator.name.label("indicator_name"),
            Indicator.unit.label("unit"),
            County.name.label("county"),
            Observation.year,
            Observation.value,
        )
        .join(Dataset,   Observation.dataset_id   == Dataset.id)
        .join(Indicator, Observation.indicator_id == Indicator.id)
        .join(County,    Observation.county_id    == County.id)
    )


# ---------------------------------------------------------------------------
# Public: system summary
# ---------------------------------------------------------------------------

def get_system_summary(db: Session) -> SystemSummary:
    """
    Return overall statistics about the database contents.

    Counts datasets, indicators, counties, and observations.
    Also returns the min/max year present and per-dataset observation counts.

    Used by: GET /api/v1/summary/
    """
    total_datasets     = db.query(func.count(Dataset.id)).scalar()     or 0
    total_indicators   = db.query(func.count(Indicator.id)).scalar()   or 0
    total_counties     = db.query(func.count(County.id)).scalar()      or 0
    total_observations = db.query(func.count(Observation.id)).scalar() or 0
    year_min           = db.query(func.min(Observation.year)).scalar()
    year_max           = db.query(func.max(Observation.year)).scalar()

    per_dataset = (
        db.query(Dataset.name, func.count(Observation.id).label("cnt"))
        .join(Observation, Observation.dataset_id == Dataset.id)
        .group_by(Dataset.name)
        .order_by(func.count(Observation.id).desc())
        .all()
    )

    return SystemSummary(
        total_datasets     = total_datasets,
        total_indicators   = total_indicators,
        total_counties     = total_counties,
        total_observations = total_observations,
        year_min           = year_min,
        year_max           = year_max,
        datasets           = [
            DatasetSummaryItem(dataset_name=row.name, observation_count=row.cnt)
            for row in per_dataset
        ],
    )


# ---------------------------------------------------------------------------
# Public: trend summary
# ---------------------------------------------------------------------------

def get_trend(
    db:             Session,
    indicator_name: str,
    county:         str,
    dataset_name:   str | None = None,
    year_from:      int | None = None,
    year_to:        int | None = None,
) -> TrendSummary | None:
    """
    Return how one indicator's value changes over time in one county.

    Args:
        indicator_name: Partial indicator name (ILIKE). Required.
        county:         Partial county name (ILIKE). Required.
        dataset_name:   Optional partial dataset filter (ILIKE).
        year_from:      Optional inclusive start year.
        year_to:        Optional inclusive end year.

    Returns:
        TrendSummary with a list of (year, value) points ordered by year asc,
        or None if no matching data exists.
    """
    q = _base_query(db)
    q = q.filter(Indicator.name.ilike(f"%{indicator_name}%"))
    q = q.filter(County.name.ilike(f"%{county}%"))

    if dataset_name:
        q = q.filter(Dataset.name.ilike(f"%{dataset_name}%"))
    if year_from is not None:
        q = q.filter(Observation.year >= year_from)
    if year_to is not None:
        q = q.filter(Observation.year <= year_to)

    q = q.order_by(Observation.year.asc())
    rows = q.all()

    if not rows:
        return None

    first = rows[0]
    return TrendSummary(
        dataset_name   = first.dataset_name,
        indicator_name = first.indicator_name,
        county         = first.county,
        unit           = first.unit,
        points         = [TrendPoint(year=r.year, value=r.value) for r in rows],
    )


# ---------------------------------------------------------------------------
# Public: comparison summary
# ---------------------------------------------------------------------------

def get_comparison(
    db:             Session,
    indicator_name: str,
    year:           int,
    dataset_name:   str | None = None,
) -> ComparisonSummary | None:
    """
    Return one indicator's value across all counties for a given year.

    Results are sorted by value descending (nulls last) so the highest
    county appears first — ready for a bar chart.

    Args:
        indicator_name: Partial indicator name (ILIKE). Required.
        year:           The year to compare across. Required.
        dataset_name:   Optional partial dataset filter (ILIKE).

    Returns:
        ComparisonSummary with a list of (county, value) items,
        or None if no matching data exists.
    """
    q = _base_query(db)
    q = q.filter(Indicator.name.ilike(f"%{indicator_name}%"))
    q = q.filter(Observation.year == year)

    if dataset_name:
        q = q.filter(Dataset.name.ilike(f"%{dataset_name}%"))

    q = q.order_by(Observation.value.desc().nulls_last(), County.name.asc())
    rows = q.all()

    if not rows:
        return None

    first = rows[0]
    return ComparisonSummary(
        dataset_name   = first.dataset_name,
        indicator_name = first.indicator_name,
        year           = year,
        unit           = first.unit,
        items          = [ComparisonItem(county=r.county, value=r.value) for r in rows],
    )


# ---------------------------------------------------------------------------
# Public: indicator statistics
# ---------------------------------------------------------------------------

def get_indicator_stats(
    db:             Session,
    indicator_name: str,
    county:         str | None = None,
    dataset_name:   str | None = None,
    year_from:      int | None = None,
    year_to:        int | None = None,
) -> dict | None:
    """
    Return min, max, and average value for one indicator (optionally scoped).

    Useful for dashboard widgets that show a headline stat alongside a chart.
    Returns None if no data exists for the indicator.

    Args:
        indicator_name: Partial indicator name (ILIKE). Required.
        county:         Optional partial county filter (ILIKE).
        dataset_name:   Optional partial dataset filter (ILIKE).
        year_from:      Optional inclusive start year.
        year_to:        Optional inclusive end year.

    Returns:
        Dict with keys: indicator_name, value_min, value_max, value_avg, count.
        Or None if no matching data exists.
    """
    q = (
        db.query(
            Indicator.name.label("indicator_name"),
            func.min(Observation.value).label("value_min"),
            func.max(Observation.value).label("value_max"),
            func.avg(Observation.value).label("value_avg"),
            func.count(Observation.id).label("count"),
        )
        .join(Dataset,   Observation.dataset_id   == Dataset.id)
        .join(Indicator, Observation.indicator_id == Indicator.id)
        .join(County,    Observation.county_id    == County.id)
        .filter(Indicator.name.ilike(f"%{indicator_name}%"))
    )

    if county:
        q = q.filter(County.name.ilike(f"%{county}%"))
    if dataset_name:
        q = q.filter(Dataset.name.ilike(f"%{dataset_name}%"))
    if year_from is not None:
        q = q.filter(Observation.year >= year_from)
    if year_to is not None:
        q = q.filter(Observation.year <= year_to)

    q = q.group_by(Indicator.name)
    row = q.first()

    if row is None or row.count == 0:
        return None

    return {
        "indicator_name": row.indicator_name,
        "value_min":      row.value_min,
        "value_max":      row.value_max,
        "value_avg":      round(row.value_avg, 4) if row.value_avg is not None else None,
        "count":          row.count,
    }


# ---------------------------------------------------------------------------
# Public: available years
# ---------------------------------------------------------------------------

def get_available_years(
    db:             Session,
    indicator_name: str,
    county:         str | None = None,
    dataset_name:   str | None = None,
) -> list[int]:
    """
    Return the sorted list of years for which data exists.

    Use this to populate year-range pickers in the dashboard or to
    validate year parameters before running a trend/comparison query.

    Args:
        indicator_name: Partial indicator name (ILIKE). Required.
        county:         Optional partial county filter (ILIKE).
        dataset_name:   Optional partial dataset filter (ILIKE).

    Returns:
        Sorted list of distinct integer years.  Empty list if no data.
    """
    q = (
        db.query(Observation.year)
        .join(Dataset,   Observation.dataset_id   == Dataset.id)
        .join(Indicator, Observation.indicator_id == Indicator.id)
        .join(County,    Observation.county_id    == County.id)
        .filter(Indicator.name.ilike(f"%{indicator_name}%"))
        .filter(Observation.year.isnot(None))
    )

    if county:
        q = q.filter(County.name.ilike(f"%{county}%"))
    if dataset_name:
        q = q.filter(Dataset.name.ilike(f"%{dataset_name}%"))

    q = q.distinct().order_by(Observation.year.asc())
    return [row.year for row in q.all()]
