"""
backend/app/services/observation_service.py
==============================================
Data-access logic for Observation records.

This module owns the core joined query that turns raw ORM rows into
the human-readable ObservationExpanded shape used throughout the API.

Public functions:
  filter_observations  — paginated, filtered list of expanded observations
  count_observations   — total matching rows without limit (for pagination metadata)

Internal helpers (underscore-prefixed) are kept here rather than spread
across the codebase so all observation query logic lives in one place.
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Dataset, Indicator, County, Observation
from app.schemas.observation import ObservationExpanded

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _base_query(db: Session):
    """
    Base SQLAlchemy query joining all four tables.

    Returns columns shaped to match ObservationExpanded:
      id, dataset_name, indicator_name, county, year, value.

    All public functions in this module start from this base and
    layer filters/ordering/pagination on top.
    """
    return (
        db.query(
            Observation.id,
            Dataset.name.label("dataset_name"),
            Indicator.name.label("indicator_name"),
            County.name.label("county"),
            Observation.year,
            Observation.value,
        )
        .join(Dataset,   Observation.dataset_id   == Dataset.id)
        .join(Indicator, Observation.indicator_id == Indicator.id)
        .join(County,    Observation.county_id    == County.id)
    )


def _apply_filters(
    query,
    dataset_name:   str | None,
    indicator_name: str | None,
    county:         str | None,
    year_from:      int | None,
    year_to:        int | None,
):
    """
    Attach optional WHERE clauses to an observation query.

    String filters use ILIKE (case-insensitive partial match) so that
    'census' matches 'LISGIS Census 2008' and 'population' matches
    'Total Population'.

    Args:
        query:          SQLAlchemy query object to filter.
        dataset_name:   Partial dataset name filter, or None.
        indicator_name: Partial indicator name filter, or None.
        county:         Partial county name filter, or None.
        year_from:      Inclusive start year, or None.
        year_to:        Inclusive end year, or None.

    Returns:
        The query with zero or more additional WHERE clauses attached.
    """
    if dataset_name:
        query = query.filter(Dataset.name.ilike(f"%{dataset_name}%"))
    if indicator_name:
        query = query.filter(Indicator.name.ilike(f"%{indicator_name}%"))
    if county:
        query = query.filter(County.name.ilike(f"%{county}%"))
    if year_from is not None:
        query = query.filter(Observation.year >= year_from)
    if year_to is not None:
        query = query.filter(Observation.year <= year_to)
    return query


def _row_to_expanded(row) -> ObservationExpanded:
    """Convert a SQLAlchemy named-row result to an ObservationExpanded schema."""
    return ObservationExpanded(
        id             = row.id,
        dataset_name   = row.dataset_name,
        indicator_name = row.indicator_name,
        county         = row.county,
        year           = row.year,
        value          = row.value,
    )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def filter_observations(
    db:             Session,
    dataset_name:   str | None = None,
    indicator_name: str | None = None,
    county:         str | None = None,
    year_from:      int | None = None,
    year_to:        int | None = None,
    limit:          int        = 500,
    offset:         int        = 0,
) -> list[ObservationExpanded]:
    """
    Return filtered, paginated observations as ObservationExpanded objects.

    All filter parameters are optional.  Omitting all returns the first
    `limit` rows ordered by year ascending then county alphabetically.

    Used by:
      - GET /api/v1/observations
      - POST /api/v1/ai/query  (with AI-extracted filters)
      - GET /api/v1/download/cleaned

    Args:
        db:             SQLAlchemy session.
        dataset_name:   Partial dataset name filter (ILIKE).
        indicator_name: Partial indicator name filter (ILIKE).
        county:         Partial county name filter (ILIKE).
        year_from:      Inclusive start year.
        year_to:        Inclusive end year.
        limit:          Maximum rows to return (default 500).
        offset:         Rows to skip for pagination (default 0).

    Returns:
        List of ObservationExpanded objects.  May be empty.
    """
    q = _base_query(db)
    q = _apply_filters(q, dataset_name, indicator_name, county, year_from, year_to)
    q = q.order_by(Observation.year.asc(), County.name.asc())
    q = q.limit(limit).offset(offset)

    rows = q.all()
    logger.debug("filter_observations: %d rows returned", len(rows))
    return [_row_to_expanded(r) for r in rows]


def count_observations(
    db:             Session,
    dataset_name:   str | None = None,
    indicator_name: str | None = None,
    county:         str | None = None,
    year_from:      int | None = None,
    year_to:        int | None = None,
) -> int:
    """
    Return the total number of observations matching the given filters.

    Identical filter semantics to filter_observations, but returns a count
    rather than rows.  Useful for pagination metadata (total_count) or
    sanity-checking queries before issuing a large download.

    Args:
        db:             SQLAlchemy session.
        dataset_name:   Partial dataset name filter (ILIKE).
        indicator_name: Partial indicator name filter (ILIKE).
        county:         Partial county name filter (ILIKE).
        year_from:      Inclusive start year.
        year_to:        Inclusive end year.

    Returns:
        Integer row count.
    """
    q = (
        db.query(func.count(Observation.id))
        .join(Dataset,   Observation.dataset_id   == Dataset.id)
        .join(Indicator, Observation.indicator_id == Indicator.id)
        .join(County,    Observation.county_id    == County.id)
    )
    q = _apply_filters(q, dataset_name, indicator_name, county, year_from, year_to)
    total: int = q.scalar() or 0
    logger.debug("count_observations: %d total", total)
    return total
