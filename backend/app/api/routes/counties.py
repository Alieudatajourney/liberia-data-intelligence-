"""
backend/app/api/routes/counties.py
=====================================
Routes for the /counties resource.

Endpoint:
  GET /counties/   — list all counties that appear in the database
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.county import CountyOut
from app.services.county_service import list_counties

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=list[CountyOut],
    summary="List all counties",
    description=(
        "Returns all counties present in the database, sorted alphabetically. "
        "Liberia has 15 counties. 'National' is also returned when aggregate "
        "rows are present. Use the `name` value to filter /observations."
    ),
)
def list_counties_route(db: Session = Depends(get_db)) -> list[CountyOut]:
    """
    Return all counties, ordered alphabetically.

    The list is populated during data loading — only counties that
    appear in at least one observation are returned.
    """
    results = list_counties(db=db)
    logger.debug("list_counties returned %d rows", len(results))
    return results
