"""
backend/app/api/routes/observations.py
=========================================
Routes for the /observations resource.

This is the primary data endpoint.  All filter parameters are optional
and can be combined freely.

Endpoint:
  GET /observations/   — filtered, paginated list of observations
"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.observation import ObservationExpanded
from app.services.observation_service import filter_observations

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=list[ObservationExpanded],
    summary="Query observations",
    description=(
        "The main data endpoint. Returns individual observations matching "
        "the provided filters. All filters are optional and can be combined. "
        "Results include human-readable names (dataset, indicator, county) "
        "instead of raw IDs.\n\n"
        "**Example requests:**\n"
        "- `/observations?county=Nimba&year_from=2008&year_to=2022`\n"
        "- `/observations?indicator_name=population&county=Montserrado`\n"
        "- `/observations?dataset_name=census&year_from=2008`"
    ),
)
def get_observations(
    # --- Filters ---
    dataset_name: str | None = Query(
        default=None,
        description="Filter by dataset name (case-insensitive partial match).",
        examples=["census", "employment"],
    ),
    indicator_name: str | None = Query(
        default=None,
        description="Filter by indicator name (case-insensitive partial match).",
        examples=["population", "mortality"],
    ),
    county: str | None = Query(
        default=None,
        description="Filter by county name (case-insensitive partial match).",
        examples=["Nimba", "Mont"],
    ),
    year_from: int | None = Query(
        default=None,
        ge=1970,
        description="Include observations from this year onwards (inclusive).",
    ),
    year_to: int | None = Query(
        default=None,
        le=2035,
        description="Include observations up to and including this year.",
    ),
    # --- Pagination ---
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Maximum number of rows to return. Default 500, max 5000.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of rows to skip. Used for pagination.",
    ),
    db: Session = Depends(get_db),
) -> list[ObservationExpanded]:
    """
    Return filtered observations with human-readable field names.

    All filter parameters support partial, case-insensitive matching.
    Results are ordered by year ascending, then county alphabetically.

    **Tip:** Use /indicators to find exact indicator names, then use
    a partial match here — e.g. `indicator_name=mortality` matches
    'Under-5 Mortality Rate', 'Maternal Mortality', etc.
    """
    results = filter_observations(
        db             = db,
        dataset_name   = dataset_name,
        indicator_name = indicator_name,
        county         = county,
        year_from      = year_from,
        year_to        = year_to,
        limit          = limit,
        offset         = offset,
    )
    logger.debug("get_observations returned %d rows", len(results))
    return results
