"""
backend/app/services/ingestion.py
===================================
Ingestion service: loads all Excel files from a directory,
reads every sheet, attaches metadata, and combines into one DataFrame.

Design principles:
  - NEVER assumes consistent columns across files or sheets.
  - Every row in the output knows exactly where it came from.
  - Errors in one file/sheet never abort the entire run.
  - All steps are separate functions so they can be tested individually.

Output columns guaranteed on every row:
  _dataset_name   : human-readable name derived from the filename
  _source_file    : original filename (no path)
  _source_sheet   : sheet name within that file

All other columns come from the raw data and will vary per file.
Missing columns from other files appear as NaN — this is intentional.

--- How dataset_name is derived ---

Given a file:  LISGIS_Census_2008_Population.xlsx

  Step 1  Strip the file extension
          → "LISGIS_Census_2008_Population"

  Step 2  Replace underscores and hyphens with spaces
          → "LISGIS Census 2008 Population"

  Step 3  Apply title-case to each word
          → "Lisgis Census 2008 Population"

If the filename is cryptic (e.g. "export_v3_final2.xlsx"), add it to
DATASET_NAME_OVERRIDES below to map it to a readable name.
The override takes priority over the automatic derivation.
"""

import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Override map
# ---------------------------------------------------------------------------
# Add entries here when a filename is too cryptic to derive a good name from.
# Key   = filename stem (no extension), case-sensitive, exact match.
# Value = the human-readable dataset name you want.
#
# Example:
#   "hies_2016_v2_final" : "Household Income and Expenditure Survey 2016"
#
DATASET_NAME_OVERRIDES: dict[str, str] = {
    # Add real overrides here as needed.
    # "some_cryptic_filename": "Human Readable Dataset Name",
}


# ---------------------------------------------------------------------------
# Step 1 — Discover files
# ---------------------------------------------------------------------------

def discover_excel_files(raw_dir: Path) -> list[Path]:
    """
    Return a sorted list of all .xlsx and .xls files inside raw_dir.

    Does NOT recurse into subdirectories — all files are expected
    at the top level of data/raw/.

    Args:
        raw_dir: Path to the raw data directory.

    Returns:
        Sorted list of Path objects.  Empty list if none found.
    """
    if not raw_dir.exists():
        logger.error("Raw data directory does not exist: %s", raw_dir)
        return []

    xlsx_files = list(raw_dir.glob("*.xlsx"))
    xls_files  = list(raw_dir.glob("*.xls"))

    # Exclude temp files Excel creates while a file is open (start with ~$)
    all_files = sorted(
        [f for f in xlsx_files + xls_files if not f.name.startswith("~$")]
    )

    if not all_files:
        logger.warning("No Excel files found in: %s", raw_dir)
    else:
        logger.info("Found %d Excel file(s) in %s", len(all_files), raw_dir)
        for f in all_files:
            logger.debug("  → %s", f.name)

    return all_files


# ---------------------------------------------------------------------------
# Step 2 — Derive dataset name
# ---------------------------------------------------------------------------

def derive_dataset_name(file_path: Path) -> str:
    """
    Derive a human-readable dataset name from a filename.

    Algorithm:
      1. Take the filename stem (no extension).
      2. Check DATASET_NAME_OVERRIDES first — return override if found.
      3. Replace underscores and hyphens with spaces.
      4. Collapse multiple consecutive spaces.
      5. Apply title-case.

    Examples:
      "LISGIS_Census_2008.xlsx"           → "Lisgis Census 2008"
      "employment-survey-2016.xlsx"       → "Employment Survey 2016"
      "agriculture_data_v2_final.xlsx"    → "Agriculture Data V2 Final"
      "hies_2016_v2_final.xlsx"           → uses override if set, else auto

    Args:
        file_path: Path to the Excel file.

    Returns:
        Dataset name string.
    """
    stem = file_path.stem  # filename without extension

    # Check override map first
    if stem in DATASET_NAME_OVERRIDES:
        name = DATASET_NAME_OVERRIDES[stem]
        logger.debug("Using override name for %r: %r", stem, name)
        return name

    # Replace separators with spaces
    name = re.sub(r"[_\-]+", " ", stem)

    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()

    # Title-case
    name = name.title()

    logger.debug("Derived dataset name: %r → %r", stem, name)
    return name


# ---------------------------------------------------------------------------
# Step 3 — Load a single sheet
# ---------------------------------------------------------------------------

def load_sheet(
    file_path: Path,
    sheet_name: str,
    dataset_name: str,
) -> pd.DataFrame | None:
    """
    Load one sheet from an Excel file and attach metadata columns.

    Metadata columns added (prefixed with _ to avoid clashing with data):
      _dataset_name  : derived from filename
      _source_file   : original filename only (no directory path)
      _source_sheet  : name of the sheet within the file

    All cell values are read as strings (dtype=str) so that:
      - Numbers with leading zeros are preserved (e.g. county codes)
      - Mixed-type columns don't get silently coerced
      - The normalisation/cleaning layer (next phase) handles type conversion

    Returns None (and logs a warning) if:
      - The sheet is empty or has no columns
      - Reading raises any exception

    Args:
        file_path    : Path to the Excel file.
        sheet_name   : Name of the sheet to read.
        dataset_name : Already-derived dataset name.

    Returns:
        DataFrame with metadata columns prepended, or None on failure.
    """
    logger.debug("  Reading sheet: %r from %s", sheet_name, file_path.name)

    try:
        df = pd.read_excel(
            file_path,
            sheet_name = sheet_name,
            dtype      = str,          # read everything as text — see docstring
            header     = 0,            # first row is headers
        )
    except Exception as exc:
        logger.error(
            "  Failed to read sheet %r from %s: %s",
            sheet_name, file_path.name, exc
        )
        return None

    # Skip completely empty sheets
    if df.empty:
        logger.warning(
            "  Sheet %r in %s is empty — skipping.",
            sheet_name, file_path.name
        )
        return None

    # Skip sheets that have no meaningful data columns
    if len(df.columns) == 0:
        logger.warning(
            "  Sheet %r in %s has no columns — skipping.",
            sheet_name, file_path.name
        )
        return None

    # Attach metadata as the first three columns
    # Using insert() so they appear before the data columns, not after
    df.insert(0, "_dataset_name", dataset_name)
    df.insert(1, "_source_file",  file_path.name)
    df.insert(2, "_source_sheet", str(sheet_name))

    logger.debug(
        "  Loaded sheet %r: %d rows × %d cols",
        sheet_name, len(df), len(df.columns) - 3  # subtract the 3 metadata cols
    )
    return df


# ---------------------------------------------------------------------------
# Step 4 — Load all sheets from one Excel file
# ---------------------------------------------------------------------------

def load_excel_file(file_path: Path) -> list[pd.DataFrame]:
    """
    Load every sheet from an Excel file.

    First reads the sheet names without loading data (faster, less memory),
    then calls load_sheet() for each one.

    Args:
        file_path: Path to the Excel file.

    Returns:
        List of DataFrames (one per readable, non-empty sheet).
        Empty list if the file cannot be opened or all sheets fail.
    """
    logger.info("Processing file: %s", file_path.name)

    dataset_name = derive_dataset_name(file_path)
    logger.info("  Dataset name: %r", dataset_name)

    # Get sheet names without reading data
    try:
        excel_file = pd.ExcelFile(file_path)
        sheet_names = excel_file.sheet_names
    except Exception as exc:
        logger.error("  Cannot open %s: %s", file_path.name, exc)
        return []

    logger.info("  Sheets found: %s", sheet_names)

    loaded_sheets = []
    for sheet_name in sheet_names:
        df = load_sheet(file_path, sheet_name, dataset_name)
        if df is not None:
            loaded_sheets.append(df)

    logger.info(
        "  %d / %d sheet(s) loaded successfully from %s",
        len(loaded_sheets), len(sheet_names), file_path.name
    )
    return loaded_sheets


# ---------------------------------------------------------------------------
# Step 5 — Combine all DataFrames
# ---------------------------------------------------------------------------

def combine_dataframes(dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Concatenate all DataFrames into one.

    Because different files have different columns, pd.concat with
    sort=False will:
      - Keep all columns from all files
      - Fill missing values with NaN where a column doesn't exist in a file
      - Preserve the original column order from each file

    This is the correct behaviour for heterogeneous multi-source data.
    The normalisation phase (next step) decides what to do with the NaNs.

    Args:
        dataframes: List of DataFrames from load_excel_file().

    Returns:
        One combined DataFrame.

    Raises:
        ValueError: If the input list is empty (nothing was loaded).
    """
    if not dataframes:
        raise ValueError(
            "No data to combine. "
            "Check that data/raw/ contains valid Excel files "
            "and that all sheets have at least one row."
        )

    logger.info("Combining %d sheet(s) into one DataFrame...", len(dataframes))

    combined = pd.concat(
        dataframes,
        ignore_index = True,   # reset row index — don't keep per-file indices
        sort         = False,  # preserve column order, don't sort alphabetically
    )

    logger.info(
        "Combined shape: %d rows × %d columns",
        len(combined), len(combined.columns)
    )

    # Report how many distinct datasets, files, and sheets ended up in the output
    logger.info(
        "  Distinct datasets : %d",
        combined["_dataset_name"].nunique()
    )
    logger.info(
        "  Distinct files    : %d",
        combined["_source_file"].nunique()
    )
    logger.info(
        "  Distinct sheets   : %d",
        combined["_source_sheet"].nunique()
    )

    return combined


# ---------------------------------------------------------------------------
# Step 6 — Save output
# ---------------------------------------------------------------------------

def save_combined(df: pd.DataFrame, output_path: Path) -> None:
    """
    Write the combined DataFrame to a CSV file.

    Creates the output directory if it doesn't already exist.

    Args:
        df          : The combined DataFrame.
        output_path : Full path for the output CSV file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")
    logger.info("Output written to: %s", output_path)
    logger.info("  File size: %s KB", round(output_path.stat().st_size / 1024, 1))


# ---------------------------------------------------------------------------
# Orchestrator — the single function callers invoke
# ---------------------------------------------------------------------------

def run_ingestion(raw_dir: Path, output_path: Path) -> dict:
    """
    Full ingestion pipeline: discover → load → combine → save.

    Args:
        raw_dir     : Directory containing raw Excel files (data/raw/).
        output_path : Where to write the combined CSV (data/processed/raw_combined.csv).

    Returns:
        Summary dict with counts:
        {
            "files_found"    : int,
            "files_loaded"   : int,
            "files_failed"   : int,
            "sheets_loaded"  : int,
            "sheets_skipped" : int,
            "total_rows"     : int,
            "total_columns"  : int,
            "output_path"    : str,
        }
    """
    logger.info("=" * 60)
    logger.info("Starting ingestion run")
    logger.info("  Source : %s", raw_dir)
    logger.info("  Output : %s", output_path)
    logger.info("=" * 60)

    # --- Discover ---
    excel_files = discover_excel_files(raw_dir)

    if not excel_files:
        logger.warning("Nothing to ingest. Place .xlsx or .xls files in: %s", raw_dir)
        return {
            "files_found":    0,
            "files_loaded":   0,
            "files_failed":   0,
            "sheets_loaded":  0,
            "sheets_skipped": 0,
            "total_rows":     0,
            "total_columns":  0,
            "output_path":    str(output_path),
        }

    # --- Load ---
    all_dataframes: list[pd.DataFrame] = []
    files_loaded  = 0
    files_failed  = 0

    for file_path in excel_files:
        sheets = load_excel_file(file_path)
        if sheets:
            all_dataframes.extend(sheets)
            files_loaded += 1
        else:
            files_failed += 1

    sheets_loaded  = len(all_dataframes)
    sheets_skipped = sum(
        len(pd.ExcelFile(f).sheet_names)
        for f in excel_files
        if f not in [
            # sheets that produced None are already logged as skipped
        ]
    ) - sheets_loaded

    # --- Combine ---
    try:
        combined = combine_dataframes(all_dataframes)
    except ValueError as exc:
        logger.error("Ingestion aborted: %s", exc)
        return {
            "files_found":    len(excel_files),
            "files_loaded":   files_loaded,
            "files_failed":   files_failed,
            "sheets_loaded":  0,
            "sheets_skipped": 0,
            "total_rows":     0,
            "total_columns":  0,
            "output_path":    str(output_path),
        }

    # --- Save ---
    save_combined(combined, output_path)

    summary = {
        "files_found":    len(excel_files),
        "files_loaded":   files_loaded,
        "files_failed":   files_failed,
        "sheets_loaded":  sheets_loaded,
        "sheets_skipped": max(0, sheets_skipped),
        "total_rows":     len(combined),
        "total_columns":  len(combined.columns),
        "output_path":    str(output_path),
    }

    logger.info("=" * 60)
    logger.info("Ingestion complete")
    for key, value in summary.items():
        logger.info("  %-20s: %s", key, value)
    logger.info("=" * 60)

    return summary
