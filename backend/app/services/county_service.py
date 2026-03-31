"""
backend/app/services/county_service.py
=========================================
Data-access logic for the County dimension.

Counties are global — not scoped to a dataset — and are populated
during data loading.  Only counties that appear in at least one
observation are stored.

Public functions:
  list_counties      — all counties alphabetically
  get_county_by_id   — single county by primary key, or None
  get_county_by_name — single county by exact name (case-insensitive), or None
"""

import logging
from sqlalchemy.orm import Session

from app.models.models import County

logger = logging.getLogger(__name__)


def list_counties(db: Session) -> list[County]:
    """
    Return all counties ordered alphabetically.

    Returns:
        List of County ORM objects.  Liberia has 15 counties;
        'National' may also appear for aggregate rows.
    """
    results = db.query(County).order_by(County.name).all()
    logger.debug("list_counties: %d rows", len(results))
    return results


def get_county_by_id(db: Session, county_id: int) -> County | None:
    """
    Return one County by primary key, or None.

    Args:
        county_id: Integer primary key.

    Returns:
        County ORM object, or None.
    """
    return db.get(County, county_id)


def get_county_by_name(db: Session, name: str) -> County | None:
    """
    Return one County by exact name (case-insensitive), or None.

    Useful for lookups during data loading when you have a canonical
    county name and need the corresponding ORM object.

    Args:
        name: County name, e.g. 'Nimba' or 'Montserrado'.

    Returns:
        County ORM object, or None.
    """
    return (
        db.query(County)
        .filter(County.name.ilike(name))
        .first()
    )
