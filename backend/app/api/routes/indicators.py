"""
backend/app/api/routes/indicators.py
=======================================
Routes for the /indicators resource.

Endpoints:
  GET /indicators/            — list all indicators (with optional filters)
  GET /indicators/{id}        — get one indicator by ID
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.indicator import IndicatorOut
from app.services.indicator_service import list_indicators, get_indicator_by_id

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=list[IndicatorOut],
    summary="List all indicators",
    description=(
        "Returns all indicators registered in the system. "
        "Indicators are scoped to a dataset — the same name can appear "
        "under different datasets. "
        "Filter by `dataset_id` to see indicators for one specific dataset."
    ),
)
def list_indicators_route(
    search: str | None = Query(
        default=None,
        description="Optional partial name filter, e.g. 'population' or 'mortality'.",
    ),
    dataset_id: int | None = Query(
        default=None,
        description="Optional filter: only return indicators for this dataset ID.",
    ),
    db: Session = Depends(get_db),
) -> list[IndicatorOut]:
    """
    List all indicators.

    - `search=population` returns indicators whose name contains 'population'.
    - `dataset_id=1` returns only indicators belonging to dataset 1.
    - Both filters can be combined.
    """
    results = list_indicators(db=db, search=search, dataset_id=dataset_id)
    logger.debug(
        "list_indicators returned %d rows (search=%r, dataset_id=%r)",
        len(results), search, dataset_id,
    )
    return results


@router.get(
    "/{indicator_id}",
    response_model=IndicatorOut,
    summary="Get a single indicator",
    description="Returns one indicator by its integer ID.",
)
def get_indicator_route(
    indicator_id: int,
    db: Session = Depends(get_db),
) -> IndicatorOut:
    """
    Get one indicator by primary key.

    Returns 404 if the indicator does not exist.
    """
    indicator = get_indicator_by_id(db=db, indicator_id=indicator_id)
    if indicator is None:
        raise HTTPException(status_code=404, detail=f"Indicator {indicator_id} not found.")
    return indicator
