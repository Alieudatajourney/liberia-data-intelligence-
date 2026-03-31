"""
backend/app/services/dataset_service.py
==========================================
Data-access logic for the Dataset dimension.

Public functions:
  list_datasets      — all datasets, optional name filter
  get_dataset_by_id  — single dataset by primary key, or None
"""

import logging
from sqlalchemy.orm import Session

from app.models.models import Dataset

logger = logging.getLogger(__name__)


def list_datasets(
    db:     Session,
    search: str | None = None,
) -> list[Dataset]:
    """
    Return all datasets ordered by name.

    Args:
        search: Optional partial, case-insensitive name filter.
                e.g. 'census' matches 'LISGIS Census 2008'.

    Returns:
        List of Dataset ORM objects (may be empty).
    """
    q = db.query(Dataset).order_by(Dataset.name)
    if search:
        q = q.filter(Dataset.name.ilike(f"%{search}%"))

    results = q.all()
    logger.debug("list_datasets: %d rows (search=%r)", len(results), search)
    return results


def get_dataset_by_id(db: Session, dataset_id: int) -> Dataset | None:
    """
    Return one Dataset by primary key, or None if it does not exist.

    Args:
        dataset_id: Integer primary key.

    Returns:
        Dataset ORM object, or None.
    """
    return db.get(Dataset, dataset_id)
