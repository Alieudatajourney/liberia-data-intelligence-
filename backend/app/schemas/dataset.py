"""
backend/app/schemas/dataset.py
================================
Pydantic schemas for the Dataset resource.

Used by FastAPI to:
  - Validate response data before sending it to the client
  - Generate accurate OpenAPI documentation

Naming convention:
  DatasetBase    — fields shared across all schemas
  DatasetCreate  — fields required to create a new dataset (future use)
  DatasetOut     — what the API returns to the client
"""

from datetime import datetime
from pydantic import BaseModel, Field


class DatasetBase(BaseModel):
    """Fields shared by all dataset schemas."""

    name: str = Field(
        ...,
        description="Canonical dataset name, e.g. 'LISGIS Census 2008'",
        examples=["LISGIS Census 2008"],
    )
    description: str | None = Field(
        default=None,
        description="Optional human-readable description of the dataset.",
    )


class DatasetCreate(DatasetBase):
    """
    Schema for creating a new dataset.
    Currently unused — datasets are created by the ingestion pipeline.
    Included for completeness and future API use.
    """
    pass


class DatasetOut(DatasetBase):
    """
    Schema for dataset responses returned by the API.

    Includes the database-assigned id and created_at timestamp.
    """

    id: int = Field(..., description="Database primary key.")
    created_at: datetime = Field(..., description="When this dataset was first ingested.")

    model_config = {"from_attributes": True}
