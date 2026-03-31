"""
backend/scripts/run_ingestion.py
==================================
CLI entry point for the ingestion pipeline.

Run from the project root (liberia-data-intelligence/):

    python backend/scripts/run_ingestion.py

Or with custom paths:

    python backend/scripts/run_ingestion.py \\
        --raw-dir  data/raw \\
        --output   data/processed/raw_combined.csv

The script:
  1. Resolves absolute paths relative to the project root
  2. Configures logging
  3. Calls the ingestion service
  4. Prints a summary table
  5. Exits with code 0 on success, 1 on failure
"""

import sys
import argparse
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
# This script can be run from anywhere.
# PROJECT_ROOT is the liberia-data-intelligence/ directory.
# We add backend/ to sys.path so that "from app.xxx import yyy" works.

SCRIPT_DIR   = Path(__file__).resolve().parent          # backend/scripts/
BACKEND_DIR  = SCRIPT_DIR.parent                        # backend/
PROJECT_ROOT = BACKEND_DIR.parent                       # liberia-data-intelligence/

sys.path.insert(0, str(BACKEND_DIR))

from app.core.logging_config import configure_logging   # noqa: E402
from app.services.ingestion import run_ingestion        # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_OUTPUT  = PROJECT_ROOT / "data" / "processed" / "raw_combined.csv"


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description = "Ingest Excel files from data/raw into a combined CSV.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  python backend/scripts/run_ingestion.py\n"
            "  python backend/scripts/run_ingestion.py --raw-dir /path/to/raw\n"
            "  python backend/scripts/run_ingestion.py --output data/processed/out.csv\n"
        ),
    )
    parser.add_argument(
        "--raw-dir",
        type    = Path,
        default = DEFAULT_RAW_DIR,
        help    = f"Directory containing raw Excel files (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--output",
        type    = Path,
        default = DEFAULT_OUTPUT,
        help    = f"Output CSV path (default: {DEFAULT_OUTPUT})",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    """
    Runs the ingestion pipeline.
    Returns exit code: 0 = success, 1 = failure.
    """
    args = build_parser().parse_args()

    # Configure logging before doing anything else
    configure_logging()
    logger = logging.getLogger(__name__)

    # Resolve paths to absolute
    raw_dir     = args.raw_dir.resolve()
    output_path = args.output.resolve()

    logger.info("Project root : %s", PROJECT_ROOT)
    logger.info("Raw dir      : %s", raw_dir)
    logger.info("Output       : %s", output_path)

    # Run the pipeline
    try:
        summary = run_ingestion(raw_dir=raw_dir, output_path=output_path)
    except Exception as exc:
        logger.error("Ingestion failed with unexpected error: %s", exc, exc_info=True)
        return 1

    # Print summary table to stdout (always visible, even if log level is high)
    print("\n" + "─" * 40)
    print("  INGESTION SUMMARY")
    print("─" * 40)
    for key, value in summary.items():
        print(f"  {key:<22} {value}")
    print("─" * 40 + "\n")

    # Non-zero failures are a warning, not a fatal error
    if summary.get("files_failed", 0) > 0:
        logger.warning(
            "%d file(s) could not be loaded. Check the logs above for details.",
            summary["files_failed"],
        )

    # Return failure if nothing was produced
    if summary.get("total_rows", 0) == 0:
        logger.error("No rows were written to output. Check that data/raw/ has valid Excel files.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
