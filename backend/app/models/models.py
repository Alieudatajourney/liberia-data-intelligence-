"""
backend/app/models/models.py
==============================
SQLAlchemy ORM models for the Liberia Public Data Intelligence system.

Tables:
  datasets      — one row per ingested source dataset
  indicators    — one row per (indicator_name, dataset) pair
  counties      — canonical list of Liberia counties
  observations  — the core fact table: one row = one measurement

--- Relationship design ---

  datasets  ──< indicators   (one dataset has many indicators)
  datasets  ──< observations (one dataset has many observations)
  indicators ──< observations (one indicator has many observations)
  counties  ──< observations (one county has many observations)

--- Why dataset is separated from indicator ---

An indicator named "Total Population" in the 2008 Census and
"Total Population" in a 2022 survey are treated as DIFFERENT indicators
because they may have different methodologies, units, or coverage.
Linking indicators to their source dataset preserves that context
and prevents false equivalences across datasets.

--- Why this schema scales ---

  - Dimension tables (datasets, indicators, counties) are small and stable.
    They act as lookup tables that observations reference by integer ID.
  - The observations table only stores raw numbers (no repeated text).
    This keeps the table narrow and fast to query.
  - Indexes on (county_id, year) and (indicator_id) support the most
    common query patterns: "all values for a county" and "all values
    for an indicator".
  - Adding new datasets never changes the schema — you just insert new
    rows into the dimension tables.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

# Import Base from the session module so all models share the same metadata.
# This is what allows Base.metadata.create_all(engine) to find all tables.
from app.db.session import Base


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------

class Dataset(Base):
    """
    One row per source dataset (one Excel file = one dataset).

    The name must be unique — it is the deduplication key used by the loader.
    """
    __tablename__ = "datasets"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships — allow navigation: dataset.indicators, dataset.observations
    indicators   = relationship("Indicator",   back_populates="dataset",  cascade="all, delete-orphan")
    observations = relationship("Observation", back_populates="dataset",  cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Dataset id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# indicators
# ---------------------------------------------------------------------------

class Indicator(Base):
    """
    One row per (indicator_name, dataset) pair.

    The same indicator name can exist under different datasets
    (they are distinct because the source and methodology may differ).

    The unique constraint is on (name, dataset_id) — not just name.
    """
    __tablename__ = "indicators"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(512), nullable=False)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    unit       = Column(String(128), nullable=True)   # populated in a future phase

    # Unique constraint: the same indicator name cannot appear twice
    # under the same dataset.
    __table_args__ = (
        UniqueConstraint("name", "dataset_id", name="uq_indicator_per_dataset"),
    )

    dataset      = relationship("Dataset",     back_populates="indicators")
    observations = relationship("Observation", back_populates="indicator")

    def __repr__(self) -> str:
        return f"<Indicator id={self.id} name={self.name!r} dataset_id={self.dataset_id}>"


# ---------------------------------------------------------------------------
# counties
# ---------------------------------------------------------------------------

class County(Base):
    """
    Canonical lookup table for Liberia's 15 counties (+ "National").

    County names are global — "Nimba" is the same county regardless of
    which dataset mentions it.  Storing it once here avoids repeating
    the string in every observation row.
    """
    __tablename__ = "counties"

    id   = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)

    observations = relationship("Observation", back_populates="county")

    def __repr__(self) -> str:
        return f"<County id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# observations
# ---------------------------------------------------------------------------

class Observation(Base):
    """
    Core fact table — one row = one data point.

    Each observation references:
      - which dataset it came from   (dataset_id)
      - what is being measured       (indicator_id → also implies the dataset)
      - where it was measured        (county_id)
      - when it was measured         (year)
      - the numeric result           (value)

    The unique constraint prevents loading the same data point twice.
    If a re-load occurs, duplicates are detected and skipped.

    Note: dataset_id is stored redundantly here (indicator already links to
    dataset) for query performance — it avoids a join when filtering by dataset.
    """
    __tablename__ = "observations"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id   = Column(Integer, ForeignKey("datasets.id"),   nullable=False)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=False)
    county_id    = Column(Integer, ForeignKey("counties.id"),   nullable=False)
    year         = Column(Integer, nullable=False)
    value        = Column(Float,   nullable=True)    # nullable: some cells are legitimately blank

    __table_args__ = (
        # Prevents loading the same (what, where, when) combination twice
        UniqueConstraint(
            "dataset_id", "indicator_id", "county_id", "year",
            name="uq_observation",
        ),
        # Speed up "all observations for a county in a year range" queries
        Index("ix_obs_county_year", "county_id", "year"),
        # Speed up "all observations for an indicator" queries
        Index("ix_obs_indicator_id", "indicator_id"),
    )

    dataset   = relationship("Dataset",   back_populates="observations")
    indicator = relationship("Indicator", back_populates="observations")
    county    = relationship("County",    back_populates="observations")

    def __repr__(self) -> str:
        return (
            f"<Observation dataset_id={self.dataset_id} "
            f"indicator_id={self.indicator_id} "
            f"county_id={self.county_id} "
            f"year={self.year} value={self.value}>"
        )
