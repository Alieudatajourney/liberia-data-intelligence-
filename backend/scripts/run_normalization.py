"""
backend/scripts/run_normalization.py
======================================
CLI entry point for the normalization pipeline.

Run from the project root (liberia-data-intelligence/):

    python backend/scripts/run_normalization.py

Or with custom paths:

    python backend/scripts/run_normalization.py \\
        --input  data/processed/raw_combined.csv \\
        --output data/processed

Prerequisites:
    Run the ingestion pipeline first:
        python backend/scripts/run_ingestion.py
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
from app.services.normalizer import run_normalization

DEFAULT_INPUT  = PROJECT_ROOT / "data" / "processed" / "raw_combined.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description = "Normalize raw_combined.csv into a unified indicator schema.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Outputs:\n"
            "  data/processed/cleaned_observations.csv  — normalised observations\n"
            "  data/processed/flagged_rows.csv          — rows that could not be mapped\n\n"
            "Examples:\n"
            "  python backend/scripts/run_normalization.py\n"
            "  python backend/scripts/run_normalization.py --input data/processed/raw_combined.csv\n"
        ),
    )
    parser.add_argument(
        "--input",
        type    = Path,
        default = DEFAULT_INPUT,
        help    = f"Path to raw_combined.csv (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type    = Path,
        default = DEFAULT_OUTPUT,
        help    = f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    configure_logging()
    logger = logging.getLogger(__name__)

    input_path  = args.input.resolve()
    output_dir  = args.output.resolve()

    logger.info("Input  : %s", input_path)
    logger.info("Output : %s", output_dir)

    try:
        summary = run_normalization(input_path=input_path, output_dir=output_dir)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("Normalization failed: %s", exc, exc_info=True)
        return 1

    # Print summary table
    print("\n" + "─" * 44)
    print("  NORMALIZATION SUMMARY")
    print("─" * 44)
    for key, value in summary.items():
        if key == "flag_breakdown":
            if value:
                print(f"  {'flag_breakdown':<28}")
                for reason, count in sorted(value.items(), key=lambda x: -x[1]):
                    print(f"    {reason:<26}: {count}")
        else:
            print(f"  {key:<28}: {value}")
    print("─" * 44 + "\n")

    if summary.get("groups_fully_flagged", 0) > 0:
        logger.warning(
            "%d group(s) were fully flagged — check flagged_rows.csv for details.",
            summary["groups_fully_flagged"],
        )

    if summary.get("clean_observations", 0) == 0:
        logger.error("No clean observations produced. Check logs and flagged_rows.csv.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
