"""
backend/app/schemas/indicator.py
===================================
Pydantic schemas for the Indicator resource.

An indicator represents what is being measured, e.g.:
  "Total Population", "Employment Rate", "Under-5 Mortality Rate"

Indicators are scoped to a dataset — the same name under different
datasets produces two separate indicator records (different methodology/units).
"""

from pydantic import BaseModel, Field


class IndicatorBase(BaseModel):
    """Fields shared by all indicator schemas."""

    name: str = Field(
        ...,
        description="Canonical indicator name, e.g. 'Total Population'",
        examples=["Total Population", "Employment Rate"],
    )
    dataset_id: int = Field(
        ...,
        description="ID of the dataset this indicator belongs to.",
    )
    unit: str | None = Field(
        default=None,
        description="Unit of measurement, e.g. 'percent', 'count', 'per 1000'. "
                    "Null if not specified in the source data.",
        examples=["percent", "count", None],
    )


class IndicatorCreate(IndicatorBase):
    """
    Schema for creating a new indicator.
    Currently handled by the ingestion pipeline, not the API.
    """
    pass


class IndicatorOut(IndicatorBase):
    """Schema for indicator responses returned by the API."""

    id: int = Field(..., description="Database primary key.")

    model_config = {"from_attributes": True}
