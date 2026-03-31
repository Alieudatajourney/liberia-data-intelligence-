"""
backend/app/api/routes/download.py
=====================================
Route for downloading data as a CSV file.

Endpoint:
  GET /download/cleaned   — export filtered observations as CSV

Accepts the same filter parameters as GET /observations.
Returns a streaming CSV file with a Content-Disposition header
so the browser prompts "Save As" automatically.

Why streaming?
  For large result sets, building a giant string in memory before
  sending is wasteful.  StreamingResponse lets us yield rows as they
  are generated — lower peak memory, faster first-byte time.

In v1, we buffer the full CSV in memory (simpler), with a note on
how to convert to true streaming for large datasets.
"""

import io
import csv
import logging
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.observation_service import filter_observations

logger = logging.getLogger(__name__)
router = APIRouter()

# Hard cap on download size to prevent accidental huge queries
DOWNLOAD_MAX_ROWS = 50_000


@router.get(
    "/cleaned",
    summary="Download observations as CSV",
    description=(
        "Export filtered observations as a downloadable CSV file. "
        "Accepts the same filters as GET /observations. "
        "Maximum 50,000 rows per download.\n\n"
        "**Example:** `/download/cleaned?county=Nimba&year_from=2008`"
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "A CSV file containing the filtered observations.",
        }
    },
)
def download_cleaned(
    dataset_name: str | None = Query(
        default=None,
        description="Filter by dataset name (partial match).",
    ),
    indicator_name: str | None = Query(
        default=None,
        description="Filter by indicator name (partial match).",
    ),
    county: str | None = Query(
        default=None,
        description="Filter by county name (partial match).",
    ),
    year_from: int | None = Query(
        default=None,
        ge=1970,
        description="Start year (inclusive).",
    ),
    year_to: int | None = Query(
        default=None,
        le=2035,
        description="End year (inclusive).",
    ),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Export matching observations as a UTF-8 CSV file.

    The file is named `liberia_observations.csv`.
    Column order: dataset_name, indicator_name, county, year, value.
    """
    logger.info(
        "CSV download requested: dataset=%r indicator=%r county=%r years=%s–%s",
        dataset_name, indicator_name, county, year_from, year_to,
    )

    results = filter_observations(
        db             = db,
        dataset_name   = dataset_name,
        indicator_name = indicator_name,
        county         = county,
        year_from      = year_from,
        year_to        = year_to,
        limit          = DOWNLOAD_MAX_ROWS,
        offset         = 0,
    )

    logger.info("CSV download: %d rows", len(results))

    # Build CSV in memory using io.StringIO
    # For very large exports (>50k rows), replace with a generator and
    # yield rows one at a time instead of building the full string.
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["dataset_name", "indicator_name", "county", "year", "value"],
        extrasaction="ignore",  # ignore any extra fields (e.g. id, _source_*)
    )
    writer.writeheader()

    for obs in results:
        writer.writerow({
            "dataset_name":   obs.dataset_name,
            "indicator_name": obs.indicator_name,
            "county":         obs.county,
            "year":           obs.year,
            "value":          obs.value if obs.value is not None else "",
        })

    output.seek(0)

    return StreamingResponse(
        content    = iter([output.getvalue()]),
        media_type = "text/csv",
        headers    = {
            "Content-Disposition": 'attachment; filename="liberia_observations.csv"',
            "X-Row-Count": str(len(results)),
        },
    )
