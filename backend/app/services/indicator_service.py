"""
backend/app/services/indicator_service.py
============================================
Data-access logic for the Indicator dimension.

Public functions:
  list_indicators      — all indicators, optional name + dataset filters
  get_indicator_by_id  — single indicator by primary key, or None
"""

import logging
from sqlalchemy.orm import Session

from app.models.models import Indicator

logger = logging.getLogger(__name__)


def list_indicators(
    db:         Session,
    search:     str | None = None,
    dataset_id: int | None = None,
) -> list[Indicator]:
    """
    Return all indicators ordered by name.

    Args:
        search:     Optional partial, case-insensitive name filter.
                    e.g. 'mortality' matches 'Under-5 Mortality Rate'.
        dataset_id: Optional filter to restrict results to one dataset.

    Returns:
        List of Indicator ORM objects (may be empty).
    """
    q = db.query(Indicator).order_by(Indicator.name)

    if search:
        q = q.filter(Indicator.name.ilike(f"%{search}%"))
    if dataset_id is not None:
        q = q.filter(Indicator.dataset_id == dataset_id)

    results = q.all()
    logger.debug(
        "list_indicators: %d rows (search=%r, dataset_id=%r)",
        len(results), search, dataset_id,
    )
    return results


def get_indicator_by_id(db: Session, indicator_id: int) -> Indicator | None:
    """
    Return one Indicator by primary key, or None if it does not exist.

    Args:
        indicator_id: Integer primary key.

    Returns:
        Indicator ORM object, or None.
    """
    return db.get(Indicator, indicator_id)
