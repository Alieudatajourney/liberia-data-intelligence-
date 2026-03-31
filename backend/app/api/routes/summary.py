"""
backend/app/api/routes/summary.py
====================================
Routes for aggregate summary endpoints.

Endpoints:
  GET /summary/          — system-wide statistics
  GET /summary/trend     — time-series for one indicator + county
  GET /summary/compare   — cross-county comparison for one indicator + year
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.summary import SystemSummary, TrendSummary, ComparisonSummary
from app.services.summary_service import get_system_summary, get_trend, get_comparison

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=SystemSummary,
    summary="System overview",
    description=(
        "Returns high-level statistics: total datasets, indicators, "
        "counties, observations, year range, and per-dataset row counts. "
        "Useful for dashboard header widgets."
    ),
)
def system_summary(db: Session = Depends(get_db)) -> SystemSummary:
    """Return overall database statistics."""
    return get_system_summary(db)


@router.get(
    "/trend",
    response_model=TrendSummary,
    summary="Trend over time",
    description=(
        "Returns how one indicator's value changes over time for one county. "
        "The response is shaped for direct use in a line chart: "
        "a list of `{year, value}` points in ascending year order.\n\n"
        "**Example:** `/summary/trend?indicator_name=Total Population&county=Nimba`"
    ),
)
def trend_summary(
    indicator_name: str = Query(
        ...,
        description="Indicator name (partial match). Required.",
        examples=["Total Population", "Employment Rate"],
    ),
    county: str = Query(
        ...,
        description="County name (partial match). Required.",
        examples=["Nimba", "Montserrado"],
    ),
    dataset_name: str | None = Query(
        default=None,
        description="Optional: narrow to a specific dataset (partial match).",
    ),
    year_from: int | None = Query(
        default=None,
        ge=1970,
        description="Optional: start year.",
    ),
    year_to: int | None = Query(
        default=None,
        le=2035,
        description="Optional: end year.",
    ),
    db: Session = Depends(get_db),
) -> TrendSummary:
    """
    Return a time-series for one indicator in one county.

    Returns 404 if no data matches the given indicator + county combination.
    """
    result = get_trend(
        db             = db,
        indicator_name = indicator_name,
        county         = county,
        dataset_name   = dataset_name,
        year_from      = year_from,
        year_to        = year_to,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No data found for indicator '{indicator_name}' "
                f"in county '{county}'. "
                f"Use /indicators to browse available indicators."
            ),
        )
    return result


@router.get(
    "/compare",
    response_model=ComparisonSummary,
    summary="Compare counties",
    description=(
        "Returns one indicator's value across all counties for a given year. "
        "The response is shaped for a bar chart: "
        "a list of `{county, value}` items sorted by value descending.\n\n"
        "**Example:** `/summary/compare?indicator_name=Employment Rate&year=2016`"
    ),
)
def comparison_summary(
    indicator_name: str = Query(
        ...,
        description="Indicator name (partial match). Required.",
        examples=["Employment Rate", "Total Population"],
    ),
    year: int = Query(
        ...,
        ge=1970,
        le=2035,
        description="Year to compare across. Required.",
        examples=[2008, 2016, 2022],
    ),
    dataset_name: str | None = Query(
        default=None,
        description="Optional: narrow to a specific dataset (partial match).",
    ),
    db: Session = Depends(get_db),
) -> ComparisonSummary:
    """
    Return all counties' values for one indicator in one year.

    Returns 404 if no data matches the given indicator + year combination.
    """
    result = get_comparison(
        db             = db,
        indicator_name = indicator_name,
        year           = year,
        dataset_name   = dataset_name,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No data found for indicator '{indicator_name}' "
                f"in year {year}. "
                f"Use /indicators and /observations to verify available data."
            ),
        )
    return result
