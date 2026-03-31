"""
backend/app/services/db_loader_service.py
==========================================
Database loading service — reads cleaned_observations.csv and inserts
rows into PostgreSQL following the strict loading order:

  Step 1 → datasets     (no foreign key dependencies)
  Step 2 → indicators   (depends on dataset_id)
  Step 3 → counties     (no foreign key dependencies)
  Step 4 → observations (depends on all three IDs)

--- Deduplication strategy ---

Dimension tables (datasets, indicators, counties) use a GET-OR-CREATE pattern:

  1. Check an in-memory Python dict (cache) for the key.
  2. If found → return the cached ID immediately (zero DB queries).
  3. If not found → query the database.
  4. If a row exists in the DB → cache its ID and return it.
  5. If no row exists → insert a new row, cache the new ID, return it.

This cache-first approach means each unique entity is only looked up
or inserted ONCE, regardless of how many observations reference it.
For a dataset with 15 counties × 20 indicators = 300 row lookups
reduced to 35 (15 + 20).

Observations are loaded in configurable batches (default: 500 rows).
Each batch is committed atomically.  If a batch fails:
  - The error is logged.
  - Processing continues with the next batch.
  - Rows in the failed batch are counted as "failed".

Duplicate observations (same dataset, indicator, county, year) are caught
by the database UNIQUE constraint and counted as "skipped" — not errors.

--- Limitations (v1) ---

See the module-level docstring section at the bottom of this file.
"""

import logging
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.models import Dataset, Indicator, County, Observation

logger = logging.getLogger(__name__)

# Number of observation rows inserted per database transaction.
# Larger = fewer commits (faster) but more memory per batch.
# Smaller = more commits (slower) but easier to recover from failures.
BATCH_SIZE = 500


# ===========================================================================
# Dimension: caches
# ===========================================================================
# Each cache maps a lookup key to a database primary key (integer ID).
# They live in memory for the duration of one load run.

DatasetCache   = dict[str, int]                   # dataset_name → dataset.id
IndicatorCache = dict[tuple[str, int], int]        # (indicator_name, dataset_id) → indicator.id
CountyCache    = dict[str, int]                    # county_name → county.id


# ===========================================================================
# Step 1 — Datasets
# ===========================================================================

def get_or_create_dataset(
    db: Session,
    name: str,
    cache: DatasetCache,
) -> int:
    """
    Return the database ID for a dataset, creating it if needed.

    Args:
        db    : Active SQLAlchemy session.
        name  : Canonical dataset name (from cleaned_observations.csv).
        cache : In-memory dict shared across all calls in this run.

    Returns:
        Integer primary key from the datasets table.
    """
    # Cache hit — no DB query needed
    if name in cache:
        return cache[name]

    # DB lookup
    existing = db.query(Dataset).filter_by(name=name).first()
    if existing:
        cache[name] = existing.id
        logger.debug("  Dataset already exists: %r (id=%d)", name, existing.id)
        return existing.id

    # Insert new dataset
    new_dataset = Dataset(name=name)
    db.add(new_dataset)
    db.flush()  # flush to get the auto-generated id without committing yet
    cache[name] = new_dataset.id
    logger.info("  Inserted dataset: %r (id=%d)", name, new_dataset.id)
    return new_dataset.id


# ===========================================================================
# Step 2 — Indicators
# ===========================================================================

def get_or_create_indicator(
    db: Session,
    name: str,
    dataset_id: int,
    cache: IndicatorCache,
) -> int:
    """
    Return the database ID for an indicator, creating it if needed.

    Indicators are scoped to a dataset: the same name under different
    datasets produces two separate indicator rows.

    Args:
        db         : Active SQLAlchemy session.
        name       : Canonical indicator name.
        dataset_id : ID of the parent dataset (already loaded in Step 1).
        cache      : In-memory dict shared across all calls in this run.

    Returns:
        Integer primary key from the indicators table.
    """
    key = (name, dataset_id)

    if key in cache:
        return cache[key]

    existing = db.query(Indicator).filter_by(name=name, dataset_id=dataset_id).first()
    if existing:
        cache[key] = existing.id
        logger.debug("  Indicator already exists: %r dataset_id=%d (id=%d)", name, dataset_id, existing.id)
        return existing.id

    new_indicator = Indicator(name=name, dataset_id=dataset_id)
    db.add(new_indicator)
    db.flush()
    cache[key] = new_indicator.id
    logger.debug("  Inserted indicator: %r (id=%d)", name, new_indicator.id)
    return new_indicator.id


# ===========================================================================
# Step 3 — Counties
# ===========================================================================

def get_or_create_county(
    db: Session,
    name: str,
    cache: CountyCache,
) -> int:
    """
    Return the database ID for a county, creating it if needed.

    Counties are global — not scoped to any dataset.

    Args:
        db    : Active SQLAlchemy session.
        name  : Canonical county name (already normalized by the normalizer).
        cache : In-memory dict shared across all calls in this run.

    Returns:
        Integer primary key from the counties table.
    """
    if name in cache:
        return cache[name]

    existing = db.query(County).filter_by(name=name).first()
    if existing:
        cache[name] = existing.id
        logger.debug("  County already exists: %r (id=%d)", name, existing.id)
        return existing.id

    new_county = County(name=name)
    db.add(new_county)
    db.flush()
    cache[name] = new_county.id
    logger.info("  Inserted county: %r (id=%d)", name, new_county.id)
    return new_county.id


# ===========================================================================
# Step 1–3 combined: load all dimension rows
# ===========================================================================

def load_dimensions(
    db: Session,
    df: pd.DataFrame,
) -> tuple[DatasetCache, IndicatorCache, CountyCache]:
    """
    Pass 1: scan all rows and insert every unique dataset, indicator,
    and county before any observations are inserted.

    Doing this in a single upfront pass means every observation in Pass 2
    can get its foreign key IDs from the in-memory cache — no DB queries
    during observation loading.

    Args:
        db : Active SQLAlchemy session.
        df : The full cleaned_observations DataFrame.

    Returns:
        (dataset_cache, indicator_cache, county_cache)
    """
    logger.info("Pass 1: Loading dimension tables...")

    dataset_cache:   DatasetCache   = {}
    indicator_cache: IndicatorCache = {}
    county_cache:    CountyCache    = {}

    # --- Step 1: datasets ---
    unique_datasets = df["dataset_name"].dropna().unique()
    logger.info("  Unique datasets:   %d", len(unique_datasets))
    for name in unique_datasets:
        get_or_create_dataset(db, str(name), dataset_cache)

    # --- Step 2: indicators (needs dataset IDs from Step 1) ---
    unique_indicators = df[["indicator_name", "dataset_name"]].drop_duplicates()
    logger.info("  Unique indicators: %d", len(unique_indicators))
    for _, row in unique_indicators.iterrows():
        dataset_id = dataset_cache.get(str(row["dataset_name"]))
        if dataset_id is None:
            logger.warning("  Skipping indicator %r — dataset not found", row["indicator_name"])
            continue
        get_or_create_indicator(db, str(row["indicator_name"]), dataset_id, indicator_cache)

    # --- Step 3: counties ---
    unique_counties = df["county"].dropna().unique()
    logger.info("  Unique counties:   %d", len(unique_counties))
    for name in unique_counties:
        get_or_create_county(db, str(name), county_cache)

    # Commit all dimension rows as a single transaction.
    # If this fails, we abort early — observations cannot be loaded without IDs.
    db.commit()
    logger.info(
        "  Dimensions committed: %d datasets, %d indicators, %d counties",
        len(dataset_cache), len(indicator_cache), len(county_cache),
    )

    return dataset_cache, indicator_cache, county_cache


# ===========================================================================
# Step 4 — Observations
# ===========================================================================

def load_observations(
    db: Session,
    df: pd.DataFrame,
    dataset_cache:   DatasetCache,
    indicator_cache: IndicatorCache,
    county_cache:    CountyCache,
    batch_size:      int = BATCH_SIZE,
) -> dict[str, int]:
    """
    Pass 2: insert all observations using pre-loaded dimension IDs.

    Processes rows in batches.  Each batch is committed independently.
    Failures in one batch do not affect other batches.

    Duplicate detection:
      The database UNIQUE constraint on observations catches any duplicate
      (dataset_id, indicator_id, county_id, year) combination.
      SQLAlchemy raises IntegrityError, which we catch and count as "skipped".

    Args:
        db              : Active SQLAlchemy session.
        df              : The full cleaned_observations DataFrame.
        dataset_cache   : dataset_name → dataset_id
        indicator_cache : (indicator_name, dataset_id) → indicator_id
        county_cache    : county_name → county_id
        batch_size      : How many rows to insert per transaction.

    Returns:
        {"inserted": N, "skipped": N, "failed": N}
    """
    logger.info("Pass 2: Loading observations (batch_size=%d)...", batch_size)

    inserted = 0
    skipped  = 0
    failed   = 0
    total    = len(df)

    # Split the DataFrame into chunks of batch_size rows
    batches = [df.iloc[i : i + batch_size] for i in range(0, total, batch_size)]
    logger.info("  Total rows: %d → %d batch(es)", total, len(batches))

    for batch_num, batch in enumerate(batches, start=1):
        batch_inserted = 0
        batch_skipped  = 0
        batch_failed   = 0

        for row_idx, row in batch.iterrows():
            # --- Resolve foreign keys from cache ---
            dataset_name   = str(row.get("dataset_name",   ""))
            indicator_name = str(row.get("indicator_name", ""))
            county_name    = str(row.get("county",         ""))

            dataset_id = dataset_cache.get(dataset_name)
            if dataset_id is None:
                logger.warning("  Row %s: unknown dataset %r — skipping", row_idx, dataset_name)
                batch_failed += 1
                continue

            indicator_id = indicator_cache.get((indicator_name, dataset_id))
            if indicator_id is None:
                logger.warning(
                    "  Row %s: unknown indicator %r for dataset_id=%d — skipping",
                    row_idx, indicator_name, dataset_id
                )
                batch_failed += 1
                continue

            county_id = county_cache.get(county_name)
            if county_id is None:
                logger.warning("  Row %s: unknown county %r — skipping", row_idx, county_name)
                batch_failed += 1
                continue

            # --- Parse year and value ---
            try:
                year = int(float(str(row.get("year", ""))))
            except (ValueError, TypeError):
                logger.warning("  Row %s: invalid year %r — skipping", row_idx, row.get("year"))
                batch_failed += 1
                continue

            raw_value = row.get("value")
            try:
                value = float(raw_value) if raw_value not in (None, "", "nan") else None
            except (ValueError, TypeError):
                value = None

            # --- Build and insert observation ---
            obs = Observation(
                dataset_id   = dataset_id,
                indicator_id = indicator_id,
                county_id    = county_id,
                year         = year,
                value        = value,
            )
            db.add(obs)

            # Flush individually so we can catch per-row integrity errors
            try:
                db.flush()
                batch_inserted += 1
            except IntegrityError:
                # Duplicate (same dataset, indicator, county, year) — not an error
                db.rollback()
                batch_skipped += 1
                logger.debug(
                    "  Row %s: duplicate observation (dataset_id=%d, indicator_id=%d, "
                    "county_id=%d, year=%d) — skipping",
                    row_idx, dataset_id, indicator_id, county_id, year,
                )
            except Exception as exc:
                db.rollback()
                batch_failed += 1
                logger.error(
                    "  Row %s: unexpected error inserting observation — %s", row_idx, exc
                )

        # Commit this batch
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("  Batch %d commit failed: %s — rolling back batch", batch_num, exc)
            batch_failed += batch_inserted  # treat all as failed
            batch_inserted = 0

        inserted += batch_inserted
        skipped  += batch_skipped
        failed   += batch_failed

        logger.info(
            "  Batch %d/%d: +%d inserted, %d skipped (dup), %d failed",
            batch_num, len(batches), batch_inserted, batch_skipped, batch_failed,
        )

    return {"inserted": inserted, "skipped": skipped, "failed": failed}


# ===========================================================================
# Orchestrator
# ===========================================================================

def run_db_load(df: pd.DataFrame, db: Session) -> dict[str, Any]:
    """
    Full database load pipeline: dimensions → observations.

    Args:
        df : cleaned_observations DataFrame (output of normalization).
        db : Active SQLAlchemy session.

    Returns:
        Summary dict:
        {
            "input_rows"          : total rows in input DataFrame
            "datasets_in_cache"   : unique datasets loaded
            "indicators_in_cache" : unique indicators loaded
            "counties_in_cache"   : unique counties loaded
            "obs_inserted"        : new observations inserted
            "obs_skipped"         : duplicate observations skipped
            "obs_failed"          : rows that could not be inserted
        }
    """
    logger.info("=" * 60)
    logger.info("Starting database load")
    logger.info("  Input rows: %d", len(df))
    logger.info("=" * 60)

    required_cols = {"dataset_name", "indicator_name", "county", "year", "value"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"Input DataFrame is missing required columns: {missing}\n"
            f"Available columns: {list(df.columns)}"
        )

    if df.empty:
        logger.warning("Input DataFrame is empty — nothing to load.")
        return {
            "input_rows": 0,
            "datasets_in_cache": 0, "indicators_in_cache": 0, "counties_in_cache": 0,
            "obs_inserted": 0, "obs_skipped": 0, "obs_failed": 0,
        }

    # --- Pass 1: dimensions ---
    dataset_cache, indicator_cache, county_cache = load_dimensions(db, df)

    # --- Pass 2: observations ---
    obs_counts = load_observations(db, df, dataset_cache, indicator_cache, county_cache)

    summary: dict[str, Any] = {
        "input_rows":           len(df),
        "datasets_in_cache":    len(dataset_cache),
        "indicators_in_cache":  len(indicator_cache),
        "counties_in_cache":    len(county_cache),
        "obs_inserted":         obs_counts["inserted"],
        "obs_skipped":          obs_counts["skipped"],
        "obs_failed":           obs_counts["failed"],
    }

    logger.info("=" * 60)
    logger.info("Database load complete")
    for key, value in summary.items():
        logger.info("  %-28s: %s", key, value)
    logger.info("=" * 60)

    return summary
