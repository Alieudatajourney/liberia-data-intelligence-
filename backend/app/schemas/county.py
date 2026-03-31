"""
backend/app/schemas/county.py
================================
Pydantic schemas for the County resource.

Counties are the geographic dimension of the system.
Liberia has 15 counties.  "National" is also accepted for aggregate rows.

Counties are global — not scoped to any dataset.
"""

from pydantic import BaseModel, Field


class CountyBase(BaseModel):
    """Fields shared by all county schemas."""

    name: str = Field(
        ...,
        description="Canonical county name, e.g. 'Montserrado', 'Nimba', or 'National'.",
        examples=["Montserrado", "Nimba", "National"],
    )


class CountyOut(CountyBase):
    """Schema for county responses returned by the API."""

    id: int = Field(..., description="Database primary key.")

    model_config = {"from_attributes": True}
