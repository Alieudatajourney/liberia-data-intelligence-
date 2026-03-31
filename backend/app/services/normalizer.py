"""
backend/app/services/normalizer.py
=====================================
Normalization service: converts raw_combined.csv into a unified schema.

Target schema (one row = one observation):
  dataset_name   : human-readable dataset name (from ingestion metadata)
  indicator_name : what is being measured (derived from column name)
  county         : standardised Liberia county name
  year           : 4-digit integer
  value          : numeric float

Outputs:
  cleaned_observations.csv  : rows that mapped cleanly
  flagged_rows.csv          : rows that could not be mapped, with reason

--- How the system adapts to different dataset structures ---

Problem: every Excel sheet can have completely different column names and layouts.
Solution: process each (source_file, source_sheet) group independently.

For each group the system:
  1. Drops all-NaN columns (columns that belong to other sheets).
  2. Scores remaining columns by how well they match known patterns.
  3. Assigns each column a role: county | year | value | ignored.
  4. Applies the correct layout handler.

Two layouts are handled:

  WIDE layout (most common):
    One row contains multiple numeric measurements.
    Each numeric column becomes a separate indicator.
    Example:
      County Name | Year | Total Population | Male Population
      Montserrado | 2008 | 1450000          | 725000
    → two observations: (Total Population, Montserrado, 2008, 1450000)
                        (Male Population,  Montserrado, 2008, 725000)

  LONG layout (less common):
    One row contains exactly one measurement with an explicit indicator column.
    Example:
      County | Indicator       | Year | Value
      Bong   | Literacy Rate   | 2022 | 72.3
    → one observation: (Literacy Rate, Bong, 2022, 72.3)

If a group's structure cannot be determined, all its rows are flagged
with a clear reason instead of silently dropped or guessed.
"""

import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ===========================================================================
# Constants
# ===========================================================================

# Canonical Liberia county names and every common alias.
# Key = lowercase cleaned alias, Value = canonical display name.
# Extend this dict when you encounter new aliases in real files.
COUNTY_LOOKUP: dict[str, str] = {
    # Official names
    "bomi":              "Bomi",
    "bong":              "Bong",
    "gbarpolu":          "Gbarpolu",
    "grand bassa":       "Grand Bassa",
    "grand cape mount":  "Grand Cape Mount",
    "grand gedeh":       "Grand Gedeh",
    "grand kru":         "Grand Kru",
    "lofa":              "Lofa",
    "margibi":           "Margibi",
    "maryland":          "Maryland",
    "montserrado":       "Montserrado",
    "nimba":             "Nimba",
    "rivercess":         "Rivercess",
    "river gee":         "River Gee",
    "sinoe":             "Sinoe",
    # Common abbreviations / aliases seen in LISGIS datasets
    "g. bassa":          "Grand Bassa",
    "g bassa":           "Grand Bassa",
    "g. cape mount":     "Grand Cape Mount",
    "g cape mount":      "Grand Cape Mount",
    "g. gedeh":          "Grand Gedeh",
    "g. kru":            "Grand Kru",
    "mont":              "Montserrado",
    "river cess":        "Rivercess",
    # National / aggregate
    "national":          "National",
    "liberia":           "National",
    "total":             "National",
    "all counties":      "National",
}

# Column name substrings that suggest a column holds county values.
# Checked in order — first match wins at the name-scoring level.
COUNTY_COLUMN_HINTS: list[str] = [
    "county",
    "district",
    "location",
    "province",
    "region",
    "area",
    "place",
]

# Column name substrings that suggest a column holds year values.
YEAR_COLUMN_HINTS: list[str] = [
    "year",
    "yr",
    "period",
    "date",
    "time",
]

# Column names that are explicitly an "indicator" dimension.
# If present, the sheet is in LONG layout.
INDICATOR_COLUMN_HINTS: list[str] = [
    "indicator",
    "indicator_name",
    "variable",
    "measure",
    "metric",
    "statistic",
]

# Column name substrings that flag a column as TEXT (never a value column).
# Used to exclude "Notes", "Source", "Remarks", etc. from value detection.
TEXT_COLUMN_HINTS: list[str] = [
    "note",
    "source",
    "remark",
    "comment",
    "description",
    "reference",
    "footnote",
    "flag",
    "status",
]

# Score threshold for column role detection.
# A column must score above this to be assigned a role.
DETECTION_THRESHOLD = 0.30

# Year range that is considered valid for this dataset.
YEAR_MIN = 1970
YEAR_MAX = 2035


# ===========================================================================
# Scoring helpers (used by column detection functions)
# ===========================================================================

def _name_score(col: str, hints: list[str]) -> float:
    """
    Score 0–1 based on how well a column name matches a list of hint strings.

    Scoring:
      1.0  — exact match (after lowercasing)
      0.85 — column name starts with a hint
      0.70 — hint is a substring of the column name
      0.0  — no match
    """
    normalized = col.lower().strip().replace("_", " ")
    for hint in hints:
        if normalized == hint:
            return 1.0
        if normalized.startswith(hint):
            return 0.85
        if hint in normalized:
            return 0.70
    return 0.0


def _county_value_score(series: pd.Series) -> float:
    """
    Score 0–1: what fraction of non-null values match a known county name.
    Used as a fallback when column name matching is inconclusive.
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return 0.0
    matches = sum(
        1 for v in non_null
        if str(v).strip().lower() in COUNTY_LOOKUP
    )
    return matches / len(non_null)


def _year_value_score(series: pd.Series) -> float:
    """
    Score 0–1: what fraction of non-null values look like 4-digit years.
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return 0.0

    def is_year(v: object) -> bool:
        try:
            n = int(float(str(v).strip()))
            return YEAR_MIN <= n <= YEAR_MAX
        except (ValueError, TypeError):
            return False

    matches = sum(1 for v in non_null if is_year(v))
    return matches / len(non_null)


def _numeric_value_score(series: pd.Series) -> float:
    """
    Score 0–1: what fraction of non-null values can be parsed as a float.
    Used to decide whether a column holds numeric measurements.
    """
    non_null = series.dropna()
    # Remove common "missing" strings before scoring
    non_null = non_null[~non_null.astype(str).str.strip().isin(
        {"", "N/A", "n/a", "NA", "-", "...", "–", "—", "x", "X", "nan", "none", "None"}
    )]
    if len(non_null) == 0:
        return 0.0

    def can_be_float(v: object) -> bool:
        try:
            float(str(v).replace(",", ""))
            return True
        except (ValueError, TypeError):
            return False

    matches = sum(1 for v in non_null if can_be_float(v))
    return matches / len(non_null)


# ===========================================================================
# Column detection (runs independently per sheet group)
# ===========================================================================

def detect_county_column(df: pd.DataFrame) -> str | None:
    """
    Identify which column holds county names.

    Strategy (combined score):
      name_score   * 0.6  +  value_score * 0.4

    The value_score checks how many values match known Liberia counties,
    so columns like "location" in health_indicators still get detected
    even though "location" is a weaker name hint.

    Returns the column name with the highest combined score above
    DETECTION_THRESHOLD, or None if no candidate clears the threshold.
    """
    candidates: dict[str, float] = {}

    for col in df.columns:
        n_score = _name_score(col, COUNTY_COLUMN_HINTS)
        v_score = _county_value_score(df[col])
        combined = n_score * 0.6 + v_score * 0.4

        if combined > DETECTION_THRESHOLD:
            candidates[col] = combined
            logger.debug("  County candidate: %-30s score=%.2f", col, combined)

    if not candidates:
        logger.warning("  Could not detect county column. Columns available: %s", list(df.columns))
        return None

    best = max(candidates, key=candidates.__getitem__)
    logger.info("  Detected county column: %r (score=%.2f)", best, candidates[best])
    return best


def detect_year_column(df: pd.DataFrame, exclude: list[str]) -> str | None:
    """
    Identify which column holds the year/time-period dimension.

    Applies both name-based and value-based scoring.
    Excludes already-assigned columns (e.g. the county column).

    Returns the best column above DETECTION_THRESHOLD, or None.
    """
    candidates: dict[str, float] = {}

    for col in df.columns:
        if col in exclude:
            continue
        n_score = _name_score(col, YEAR_COLUMN_HINTS)
        v_score = _year_value_score(df[col])
        combined = n_score * 0.6 + v_score * 0.4

        if combined > DETECTION_THRESHOLD:
            candidates[col] = combined
            logger.debug("  Year candidate: %-30s score=%.2f", col, combined)

    if not candidates:
        logger.warning("  Could not detect year column.")
        return None

    best = max(candidates, key=candidates.__getitem__)
    logger.info("  Detected year column: %r (score=%.2f)", best, candidates[best])
    return best


def detect_indicator_column(df: pd.DataFrame, exclude: list[str]) -> str | None:
    """
    Check for an explicit indicator column (signals LONG layout).

    Only uses name-based matching — an "indicator" column must be
    explicitly named as such.  Returns None for WIDE layout sheets.
    """
    for col in df.columns:
        if col in exclude:
            continue
        if _name_score(col, INDICATOR_COLUMN_HINTS) >= 0.70:
            logger.info("  Detected indicator column: %r → LONG layout", col)
            return col
    return None


def detect_value_columns(
    df: pd.DataFrame,
    exclude: list[str],
) -> list[str]:
    """
    Find all columns that hold numeric measurement values.

    A column is included as a value column if ALL of the following:
      1. It is not in the exclude list (county, year, indicator, metadata).
      2. Its name does not match TEXT_COLUMN_HINTS (notes, source, etc.).
      3. ≥50% of its non-null values can be parsed as float.

    In WIDE layout, these become the indicator names (via normalize_indicator_name).
    In LONG layout, there should be exactly one value column.
    """
    value_cols: list[str] = []

    for col in df.columns:
        if col in exclude:
            continue

        # Exclude known text columns by name
        if _name_score(col, TEXT_COLUMN_HINTS) >= 0.70:
            logger.debug("  Excluding text column: %r", col)
            continue

        score = _numeric_value_score(df[col])
        if score >= 0.50:
            value_cols.append(col)
            logger.debug("  Value column: %-30s numeric_score=%.2f", col, score)
        else:
            logger.debug(
                "  Skipping non-numeric column: %-30s score=%.2f", col, score
            )

    logger.info("  Detected %d value column(s): %s", len(value_cols), value_cols)
    return value_cols


# ===========================================================================
# Value normalization
# ===========================================================================

def normalize_county_value(raw: str) -> tuple[str | None, str | None]:
    """
    Convert a raw county string to a canonical Liberia county name.

    Returns:
        (canonical_name, None)         on success
        (None, "UNRECOGNIZED_COUNTY")  when the value is not in COUNTY_LOOKUP

    Note: "National" is an accepted value for aggregate rows.
    """
    cleaned = str(raw).strip().lower()
    if cleaned in ("", "nan", "none", "n/a"):
        return None, "EMPTY_COUNTY"

    canonical = COUNTY_LOOKUP.get(cleaned)
    if canonical:
        return canonical, None

    # Try partial match: does any county name appear in the cell value?
    for alias, canonical in COUNTY_LOOKUP.items():
        if alias in cleaned:
            logger.debug("  Partial county match: %r → %r", raw, canonical)
            return canonical, None

    return None, "UNRECOGNIZED_COUNTY"


def normalize_year_value(raw: str) -> tuple[int | None, str | None]:
    """
    Parse a raw year value to an integer.

    Returns:
        (year_int, None)           on success
        (None, "INVALID_YEAR")     when the value cannot be parsed or is out of range
    """
    cleaned = str(raw).strip()
    if cleaned in ("", "nan", "none", "n/a"):
        return None, "EMPTY_YEAR"

    # Extract first 4-digit sequence that looks like a year
    match = re.search(r"\b(19|20)\d{2}\b", cleaned)
    if match:
        year = int(match.group())
        if YEAR_MIN <= year <= YEAR_MAX:
            return year, None
        return None, "INVALID_YEAR"

    # Fallback: try direct int parse
    try:
        year = int(float(cleaned))
        if YEAR_MIN <= year <= YEAR_MAX:
            return year, None
        return None, "INVALID_YEAR"
    except (ValueError, TypeError):
        return None, "INVALID_YEAR"


def normalize_numeric_value(raw: str) -> tuple[float | None, str | None]:
    """
    Parse a raw cell value to a float.

    Returns:
        (float_value, None)           on success
        (None, None)                  when value is blank/null (silently skip)
        (None, "NON_NUMERIC_VALUE")   when value is non-blank but not parseable
    """
    cleaned = str(raw).strip()

    # Blank / missing — not an error, just skip
    if cleaned in ("", "nan", "none", "None", "N/A", "n/a", "NA", "-", "...", "–", "—", "x", "X"):
        return None, None

    # Remove thousands separators
    cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned), None
    except (ValueError, TypeError):
        return None, "NON_NUMERIC_VALUE"


def normalize_indicator_name(raw_column_name: str) -> str:
    """
    Convert a raw column name into a clean indicator name.

    Steps:
      1. Strip trailing parenthetical units: "Employment Rate (%)" → "Employment Rate"
         Only strips short parenthetical content at end of string (≤20 chars).
         Long parenthetical (acronym, description) is preserved.
      2. Replace underscores and hyphens with spaces.
      3. Collapse multiple spaces.
      4. Smart title-case: capitalise purely-lowercase words,
         preserve existing mixed-case and ALL-CAPS (e.g. HH, GDP, PCT).

    Examples:
      "Total Population"              → "Total Population"
      "Employment Rate (%)"           → "Employment Rate"
      "under5_mortality_rate"         → "Under5 Mortality Rate"
      "Urban HH (%)"                  → "Urban HH"
      "Area Planted (Ha)"             → "Area Planted"
      "Yield (MT/Ha)"                 → "Yield"
      "Forest Cover (%)"              → "Forest Cover"
      "skilled_birth_attendant_pct"   → "Skilled Birth Attendant Pct"
    """
    name = str(raw_column_name).strip()

    # Step 1: Remove trailing short parenthetical (unit suffix)
    # Only removes if content is ≤20 chars (units, not descriptions)
    name = re.sub(r"\s*\([^)]{1,20}\)\s*$", "", name)

    # Step 2: Replace separators with spaces
    name = re.sub(r"[_\-]+", " ", name)

    # Step 3: Collapse spaces
    name = re.sub(r"\s+", " ", name).strip()

    # Step 4: Smart title-case
    # Capitalise a word only if it is entirely lowercase.
    # Preserve "HH", "GDP", "Hh", "Under5", etc.
    words = name.split()
    name = " ".join(w.capitalize() if w.islower() else w for w in words)

    return name


# ===========================================================================
# Sheet group processor
# ===========================================================================

def _flag_all_rows(df: pd.DataFrame, reason: str, detail: str) -> list[dict]:
    """
    Mark every row in a group as flagged.
    Used when the sheet structure cannot be determined at all.
    """
    flagged = []
    for _, row in df.iterrows():
        entry = {"_flag_reason": reason, "_flag_detail": detail}
        entry.update(row.to_dict())
        flagged.append(entry)
    logger.warning(
        "  Flagging all %d rows: %s — %s", len(flagged), reason, detail
    )
    return flagged


def process_sheet_group(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """
    Normalise all rows from one (source_file, source_sheet) group.

    This function is the core of the adaptive design.
    It detects column roles for THIS specific group only,
    then applies the appropriate layout handler.

    Args:
        df : DataFrame slice containing only rows from one sheet.
             Still has all combined columns — most will be all-NaN.

    Returns:
        (clean_rows, flagged_rows) as lists of dicts.
        clean_rows  → feed into cleaned_observations.csv
        flagged_rows → feed into flagged_rows.csv
    """
    # Extract source tracing info (same for every row in this group)
    dataset_name = df["_dataset_name"].iloc[0] if "_dataset_name" in df.columns else ""
    source_file  = df["_source_file"].iloc[0]  if "_source_file"  in df.columns else ""
    source_sheet = df["_source_sheet"].iloc[0] if "_source_sheet" in df.columns else ""

    logger.info(
        "--- Processing group: file=%r sheet=%r (%d rows) ---",
        source_file, source_sheet, len(df)
    )

    # ── Step 1: Isolate this group's own columns ──────────────────────────
    # Drop all-NaN columns — these belong to other sheets in the combined CSV.
    # After dropping, only columns that had data in this sheet remain.
    data_df = df.dropna(axis=1, how="all").copy()

    # Separate metadata columns from data columns
    meta_cols = [c for c in data_df.columns if c.startswith("_")]
    data_cols_df = data_df.drop(columns=meta_cols)

    if data_cols_df.empty:
        return [], _flag_all_rows(
            df, "NO_DATA_COLUMNS",
            f"All columns were NaN for this group (file={source_file!r}, sheet={source_sheet!r})"
        )

    # ── Step 2: Detect column roles ───────────────────────────────────────
    assigned: list[str] = []

    county_col = detect_county_column(data_cols_df)
    if county_col:
        assigned.append(county_col)

    year_col = detect_year_column(data_cols_df, exclude=assigned)
    if year_col:
        assigned.append(year_col)

    indicator_col = detect_indicator_column(data_cols_df, exclude=assigned)
    if indicator_col:
        assigned.append(indicator_col)

    value_cols = detect_value_columns(data_cols_df, exclude=assigned)

    # ── Step 3: Check that mandatory roles are filled ─────────────────────
    if county_col is None:
        return [], _flag_all_rows(
            df, "NO_COUNTY_COLUMN",
            f"County column not detected. Columns: {list(data_cols_df.columns)}"
        )

    if year_col is None:
        return [], _flag_all_rows(
            df, "NO_YEAR_COLUMN",
            f"Year column not detected. Columns: {list(data_cols_df.columns)}"
        )

    if not value_cols:
        return [], _flag_all_rows(
            df, "NO_VALUE_COLUMNS",
            f"No numeric value columns detected. Columns: {list(data_cols_df.columns)}"
        )

    # ── Step 4: Determine layout ──────────────────────────────────────────
    # LONG: explicit indicator column + exactly one value column
    # WIDE: multiple numeric columns, each column name = indicator
    layout = "long" if (indicator_col is not None and len(value_cols) == 1) else "wide"
    logger.info("  Layout: %s", layout)

    # ── Step 5: Process each row ──────────────────────────────────────────
    clean_rows:   list[dict] = []
    flagged_rows: list[dict] = []

    for row_idx, row in data_df.iterrows():

        # --- Normalize county ---
        county, county_flag = normalize_county_value(str(row.get(county_col, "")))
        if county_flag:
            flagged_rows.append({
                "_flag_reason": county_flag,
                "_flag_detail": f"Column {county_col!r} value: {row.get(county_col)!r}",
                **row.to_dict(),
            })
            continue

        # --- Normalize year ---
        year, year_flag = normalize_year_value(str(row.get(year_col, "")))
        if year_flag:
            flagged_rows.append({
                "_flag_reason": year_flag,
                "_flag_detail": f"Column {year_col!r} value: {row.get(year_col)!r}",
                **row.to_dict(),
            })
            continue

        # --- Process by layout ---
        if layout == "long":
            # One indicator column + one value column → one observation per row
            indicator_raw = str(row.get(indicator_col, "")).strip()
            value_raw     = str(row.get(value_cols[0], ""))

            if not indicator_raw or indicator_raw.lower() in ("nan", "none", ""):
                flagged_rows.append({
                    "_flag_reason": "EMPTY_INDICATOR",
                    "_flag_detail": f"Indicator column {indicator_col!r} is blank",
                    **row.to_dict(),
                })
                continue

            value, val_flag = normalize_numeric_value(value_raw)

            if val_flag:
                flagged_rows.append({
                    "_flag_reason": val_flag,
                    "_flag_detail": (
                        f"Column {value_cols[0]!r} value: {value_raw!r} "
                        f"(indicator={indicator_raw!r})"
                    ),
                    **row.to_dict(),
                })
                continue

            if value is None:
                # Blank value — silently skip, not an error
                continue

            clean_rows.append({
                "dataset_name":  dataset_name,
                "indicator_name": normalize_indicator_name(indicator_raw),
                "county":        county,
                "year":          year,
                "value":         value,
                "_source_file":  source_file,
                "_source_sheet": source_sheet,
            })

        else:
            # WIDE layout: each value column = one indicator → melt into N observations
            row_produced_any = False

            for val_col in value_cols:
                value_raw = str(row.get(val_col, ""))
                value, val_flag = normalize_numeric_value(value_raw)

                if val_flag:
                    # Non-blank but non-numeric — flag this specific cell
                    flagged_rows.append({
                        "_flag_reason": val_flag,
                        "_flag_detail": (
                            f"Column {val_col!r} value: {value_raw!r} "
                            f"(county={county}, year={year})"
                        ),
                        **row.to_dict(),
                    })
                    continue

                if value is None:
                    # Blank cell — expected in sparse datasets, skip silently
                    continue

                clean_rows.append({
                    "dataset_name":  dataset_name,
                    "indicator_name": normalize_indicator_name(val_col),
                    "county":        county,
                    "year":          year,
                    "value":         value,
                    "_source_file":  source_file,
                    "_source_sheet": source_sheet,
                })
                row_produced_any = True

            # If a row had county + year but every value was blank → note it
            if not row_produced_any:
                logger.debug(
                    "  Row %s: county=%r year=%s — all value columns blank, skipping.",
                    row_idx, county, year
                )

    logger.info(
        "  Group done: %d clean observations, %d flagged rows",
        len(clean_rows), len(flagged_rows)
    )
    return clean_rows, flagged_rows


# ===========================================================================
# Orchestrator
# ===========================================================================

def run_normalization(input_path: Path, output_dir: Path) -> dict:
    """
    Full normalization pipeline: load → group → detect → normalize → save.

    Args:
        input_path : Path to raw_combined.csv (output of ingestion).
        output_dir : Directory to write cleaned_observations.csv and flagged_rows.csv.

    Returns:
        Summary dict:
        {
            "input_rows"           : total rows in raw_combined.csv
            "groups_processed"     : number of (file, sheet) groups
            "groups_fully_flagged" : groups where structure could not be detected
            "clean_observations"   : rows in cleaned_observations.csv
            "flagged_rows"         : rows in flagged_rows.csv
            "flag_breakdown"       : dict of {flag_reason: count}
            "clean_output"         : path to cleaned_observations.csv
            "flagged_output"       : path to flagged_rows.csv
        }
    """
    logger.info("=" * 60)
    logger.info("Starting normalization run")
    logger.info("  Input  : %s", input_path)
    logger.info("  Output : %s", output_dir)
    logger.info("=" * 60)

    # ── Load input ────────────────────────────────────────────────────────
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}\n"
            f"Run the ingestion pipeline first: python backend/scripts/run_ingestion.py"
        )

    raw_df = pd.read_csv(input_path, dtype=str)
    logger.info("Loaded %d rows × %d columns from %s", len(raw_df), len(raw_df.columns), input_path.name)

    if raw_df.empty:
        logger.warning("Input file is empty — nothing to normalize.")
        return {
            "input_rows": 0, "groups_processed": 0, "groups_fully_flagged": 0,
            "clean_observations": 0, "flagged_rows": 0, "flag_breakdown": {},
            "clean_output": str(output_dir / "cleaned_observations.csv"),
            "flagged_output": str(output_dir / "flagged_rows.csv"),
        }

    # ── Group by source ───────────────────────────────────────────────────
    # Each (source_file, source_sheet) group has its own column structure.
    group_keys = ["_source_file", "_source_sheet"]
    if not all(k in raw_df.columns for k in group_keys):
        raise ValueError(
            "Input CSV is missing metadata columns (_source_file, _source_sheet). "
            "Re-run the ingestion pipeline to regenerate raw_combined.csv."
        )

    groups = list(raw_df.groupby(group_keys, sort=False))
    logger.info("Processing %d group(s)...", len(groups))

    # ── Process each group ────────────────────────────────────────────────
    all_clean:   list[dict] = []
    all_flagged: list[dict] = []
    groups_fully_flagged = 0

    for (source_file, source_sheet), group_df in groups:
        clean, flagged = process_sheet_group(group_df.copy())
        all_clean.extend(clean)
        all_flagged.extend(flagged)
        if not clean:
            groups_fully_flagged += 1

    # ── Build output DataFrames ───────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_path   = output_dir / "cleaned_observations.csv"
    flagged_path = output_dir / "flagged_rows.csv"

    if all_clean:
        clean_df = pd.DataFrame(all_clean)
        # Canonical column order
        clean_df = clean_df[[
            "dataset_name", "indicator_name", "county", "year", "value",
            "_source_file", "_source_sheet",
        ]]
        clean_df.to_csv(clean_path, index=False, encoding="utf-8")
        logger.info("Wrote %d clean observations → %s", len(clean_df), clean_path)
    else:
        logger.warning("No clean observations produced.")
        pd.DataFrame(columns=[
            "dataset_name", "indicator_name", "county", "year", "value",
            "_source_file", "_source_sheet",
        ]).to_csv(clean_path, index=False)

    flag_breakdown: dict[str, int] = {}
    if all_flagged:
        flagged_df = pd.DataFrame(all_flagged)
        # Bring flag columns to the front for readability
        flag_cols  = ["_flag_reason", "_flag_detail"]
        other_cols = [c for c in flagged_df.columns if c not in flag_cols]
        flagged_df = flagged_df[flag_cols + other_cols]
        flagged_df.to_csv(flagged_path, index=False, encoding="utf-8")
        logger.info("Wrote %d flagged rows → %s", len(flagged_df), flagged_path)
        flag_breakdown = flagged_df["_flag_reason"].value_counts().to_dict()
    else:
        pd.DataFrame(columns=["_flag_reason", "_flag_detail"]).to_csv(
            flagged_path, index=False
        )

    # ── Summary ───────────────────────────────────────────────────────────
    summary = {
        "input_rows":           len(raw_df),
        "groups_processed":     len(groups),
        "groups_fully_flagged": groups_fully_flagged,
        "clean_observations":   len(all_clean),
        "flagged_rows":         len(all_flagged),
        "flag_breakdown":       flag_breakdown,
        "clean_output":         str(clean_path),
        "flagged_output":       str(flagged_path),
    }

    logger.info("=" * 60)
    logger.info("Normalization complete")
    logger.info("  %-28s: %s", "input_rows",           summary["input_rows"])
    logger.info("  %-28s: %s", "groups_processed",     summary["groups_processed"])
    logger.info("  %-28s: %s", "groups_fully_flagged", summary["groups_fully_flagged"])
    logger.info("  %-28s: %s", "clean_observations",   summary["clean_observations"])
    logger.info("  %-28s: %s", "flagged_rows",         summary["flagged_rows"])
    if flag_breakdown:
        logger.info("  Flag breakdown:")
        for reason, count in sorted(flag_breakdown.items(), key=lambda x: -x[1]):
            logger.info("    %-26s: %d", reason, count)
    logger.info("=" * 60)

    return summary
