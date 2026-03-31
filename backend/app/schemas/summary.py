"""
backend/app/schemas/summary.py
=================================
Pydantic schemas for summary and aggregate responses.

These are used by the /summary endpoints to return high-level
statistics without exposing raw observations.

Three types of summary:
  SystemSummary       — overall counts (datasets, indicators, counties, obs)
  TrendSummary        — how a value changes over years for one indicator/county
  ComparisonSummary   — side-by-side values across counties for one indicator/year
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# System-level summary
# ---------------------------------------------------------------------------

class DatasetSummaryItem(BaseModel):
    """One row in the per-dataset summary table."""

    dataset_name:      str = Field(..., description="Name of the dataset.")
    observation_count: int = Field(..., description="Number of observations in this dataset.")


class SystemSummary(BaseModel):
    """
    Top-level statistics for the whole system.
    Returned by GET /api/v1/summary/
    """

    total_datasets:     int = Field(..., description="Number of datasets loaded.")
    total_indicators:   int = Field(..., description="Number of distinct indicators.")
    total_counties:     int = Field(..., description="Number of distinct counties.")
    total_observations: int = Field(..., description="Total observation rows.")
    year_min: int | None    = Field(default=None, description="Earliest year in any observation.")
    year_max: int | None    = Field(default=None, description="Latest year in any observation.")
    datasets: list[DatasetSummaryItem] = Field(
        default_factory=list,
        description="Per-dataset observation counts.",
    )


# ---------------------------------------------------------------------------
# Trend summary (one indicator, one county, multiple years)
# ---------------------------------------------------------------------------

class TrendPoint(BaseModel):
    """One data point in a trend series."""

    year:  int         = Field(..., description="Year.")
    value: float | None = Field(default=None, description="Value for this year.")


class TrendSummary(BaseModel):
    """
    How one indicator changes over time in one county (or nationally).
    Returned by GET /api/v1/summary/trend
    """

    dataset_name:   str  = Field(..., description="Source dataset.")
    indicator_name: str  = Field(..., description="What is being measured.")
    county:         str  = Field(..., description="County (or 'National').")
    unit:    str | None  = Field(default=None, description="Unit of measurement.")
    points: list[TrendPoint] = Field(
        default_factory=list,
        description="Year-value pairs in ascending year order.",
    )


# ---------------------------------------------------------------------------
# Comparison summary (one indicator, one year, multiple counties)
# ---------------------------------------------------------------------------

class ComparisonItem(BaseModel):
    """One county's value in a comparison."""

    county: str         = Field(..., description="County name.")
    value:  float | None = Field(default=None, description="Value for this county.")


class ComparisonSummary(BaseModel):
    """
    One indicator's value across all counties for a given year.
    Returned by GET /api/v1/summary/compare
    """

    dataset_name:   str  = Field(..., description="Source dataset.")
    indicator_name: str  = Field(..., description="What is being measured.")
    year:           int  = Field(..., description="Year of comparison.")
    unit:    str | None  = Field(default=None, description="Unit of measurement.")
    items: list[ComparisonItem] = Field(
        default_factory=list,
        description="County-value pairs sorted by value descending.",
    )
