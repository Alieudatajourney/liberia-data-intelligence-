"""
backend/scripts/load_db.py
============================
CLI entry point: reads cleaned_observations.csv and loads it into PostgreSQL.

Run from the project root (liberia-data-intelligence/):

    python backend/scripts/load_db.py

Or with a custom input path:

    python backend/scripts/load_db.py --input data/processed/cleaned_observations.csv

Prerequisites:
  1. Database is running and DATABASE_URL is set in .env
  2. Tables are created:  python backend/scripts/init_db.py
  3. Data is normalized:  python backend/scripts/run_normalization.py
"""

import sys
import argparse
import logging
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
BACKEND_DIR  = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

sys.path.insert(0, str(BACKEND_DIR))

from app.core.logging_config import configure_logging
from app.db.session import engine, Base, SessionLocal
from app.services.db_loader_service import run_db_load

# Register all ORM models with Base.metadata
import app.models.models  # noqa: F401

import pandas as pd

DEFAULT_INPUT = PROJECT_ROOT / "data" / "processed" / "cleaned_observations.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description = "Load cleaned_observations.csv into PostgreSQL.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Steps this script performs:\n"
            "  1. Ensure all database tables exist (create_all, idempotent)\n"
            "  2. Load cleaned_observations.csv into a DataFrame\n"
            "  3. Insert datasets, indicators, counties (get-or-create)\n"
            "  4. Insert observations in batches\n"
            "  5. Print a summary\n"
        ),
    )
    parser.add_argument(
        "--input",
        type    = Path,
        default = DEFAULT_INPUT,
        help    = f"Path to cleaned_observations.csv (default: {DEFAULT_INPUT})",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    configure_logging()
    logger = logging.getLogger(__name__)

    input_path = args.input.resolve()
    logger.info("Input: %s", input_path)

    # --- Ensure tables exist ---
    # create_all() is idempotent — safe to call on every run.
    # Skips tables that already exist.
    logger.info("Ensuring database tables exist...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Tables ready.")
    except Exception as exc:
        logger.error("Cannot connect to database or create tables: %s", exc)
        logger.error(
            "Check that DATABASE_URL is set correctly in .env\n"
            "  Expected format: postgresql://USER:PASSWORD@HOST:PORT/DATABASE"
        )
        return 1

    # --- Load CSV ---
    if not input_path.exists():
        logger.error(
            "Input file not found: %s\n"
            "Run the normalization pipeline first:\n"
            "  python backend/scripts/run_normalization.py",
            input_path,
        )
        return 1

    try:
        df = pd.read_csv(input_path, dtype=str)
        logger.info("Loaded %d rows from %s", len(df), input_path.name)
    except Exception as exc:
        logger.error("Failed to read CSV: %s", exc)
        return 1

    if df.empty:
        logger.warning("CSV is empty — nothing to load.")
        return 0

    # --- Load into database ---
    db = SessionLocal()
    try:
        summary = run_db_load(df=df, db=db)
    except Exception as exc:
        logger.error("Database load failed: %s", exc, exc_info=True)
        db.rollback()
        return 1
    finally:
        db.close()

    # --- Print summary ---
    print("\n" + "─" * 44)
    print("  DATABASE LOAD SUMMARY")
    print("─" * 44)
    for key, value in summary.items():
        print(f"  {key:<28}: {value}")
    print("─" * 44 + "\n")

    if summary.get("obs_failed", 0) > 0:
        logger.warning(
            "%d observation(s) failed to insert. Check logs for details.",
            summary["obs_failed"],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
