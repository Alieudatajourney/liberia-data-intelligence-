"""
backend/app/api/routes/datasets.py
=====================================
Routes for the /datasets resource.

Endpoints:
  GET /datasets/         — list all datasets
  GET /datasets/{id}     — get one dataset by ID
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dataset import DatasetOut
from app.services.dataset_service import list_datasets, get_dataset_by_id

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=list[DatasetOut],
    summary="List all datasets",
    description=(
        "Returns every dataset that has been loaded into the system. "
        "Each dataset corresponds to one source Excel file. "
        "Use the returned `id` or `name` to filter observations."
    ),
)
def list_datasets_route(
    search: str | None = Query(
        default=None,
        description="Optional partial name filter, e.g. 'census' or '2008'.",
    ),
    db: Session = Depends(get_db),
) -> list[DatasetOut]:
    """
    List all datasets, optionally filtered by name substring.

    - `search=census` returns all datasets whose name contains 'census' (case-insensitive).
    - Omitting `search` returns all datasets.
    """
    results = list_datasets(db=db, search=search)
    logger.debug("list_datasets returned %d rows (search=%r)", len(results), search)
    return results


@router.get(
    "/{dataset_id}",
    response_model=DatasetOut,
    summary="Get a single dataset",
    description="Returns one dataset by its integer ID.",
)
def get_dataset_route(
    dataset_id: int,
    db: Session = Depends(get_db),
) -> DatasetOut:
    """
    Get one dataset by primary key.

    Returns 404 if the dataset does not exist.
    """
    dataset = get_dataset_by_id(db=db, dataset_id=dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found.")
    return dataset
