"""
backend/app/schemas/observation.py
=====================================
Pydantic schemas for the Observation resource.

An observation is a single data point:
  "In Montserrado, in 2008, the Total Population was 1,450,000."

The API returns observations in two forms:
  ObservationOut      — raw IDs (compact, for programmatic use)
  ObservationExpanded — human-readable names joined in (for display/export)

Use ObservationExpanded for the dashboard and CSV download.
Use ObservationOut when you need to pass IDs to other API calls.
"""

from pydantic import BaseModel, Field


class ObservationBase(BaseModel):
    """Core fields shared by all observation schemas."""

    dataset_id:   int   = Field(..., description="FK → datasets.id")
    indicator_id: int   = Field(..., description="FK → indicators.id")
    county_id:    int   = Field(..., description="FK → counties.id")
    year:         int   = Field(..., description="4-digit year, e.g. 2022", ge=1970, le=2035)
    value: float | None = Field(
        default=None,
        description="Numeric measurement. Null if the source cell was blank.",
    )


class ObservationOut(ObservationBase):
    """
    Observation response with raw integer foreign keys.
    Compact — suitable for downstream API consumers.
    """

    id: int = Field(..., description="Database primary key.")

    model_config = {"from_attributes": True}


class ObservationExpanded(BaseModel):
    """
    Observation response with human-readable names instead of raw IDs.
    Use this for the dashboard, CSV export, and AI query results.

    Names are resolved by joining across the dimension tables.
    """

    id:             int         = Field(..., description="Database primary key.")
    dataset_name:   str         = Field(..., description="Name of the source dataset.")
    indicator_name: str         = Field(..., description="What is being measured.")
    county:         str         = Field(..., description="Canonical county name.")
    year:           int         = Field(..., description="4-digit year.")
    value:    float | None      = Field(default=None, description="Numeric measurement.")

    model_config = {"from_attributes": True}


class ObservationFilterParams(BaseModel):
    """
    Query parameters for filtering observations.

    All fields are optional — omitting all returns all observations
    (subject to the default pagination limit).

    Used as a dependency injection model in FastAPI routes.
    """

    dataset_name:   str | None = Field(default=None, description="Filter by dataset name (partial match).")
    indicator_name: str | None = Field(default=None, description="Filter by indicator name (partial match).")
    county:         str | None = Field(default=None, description="Filter by county name.")
    year_from:      int | None = Field(default=None, description="Start year, inclusive.", ge=1970)
    year_to:        int | None = Field(default=None, description="End year, inclusive.",   le=2035)
    limit:          int        = Field(default=500,  description="Max rows to return.",    ge=1, le=5000)
    offset:         int        = Field(default=0,    description="Rows to skip (pagination).", ge=0)
