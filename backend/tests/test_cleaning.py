"""
backend/tests/test_cleaning.py
=================================
Beginner-friendly tests for the data cleaning (normalisation) step.

This file tells the story of how raw messy data becomes clean observations:

  RAW                          →  CLEAN
  ──────────────────────────────────────────────────
  "nimba"                      →  "Nimba"
  "G. Bassa"                   →  "Grand Bassa"
  "Employment Rate (%)"        →  "Employment Rate"
  "under5_mortality_rate"      →  "Under5 Mortality Rate"
  "1,450,000"                  →  1450000.0
  "2016.0"                     →  2016  (int)

  BAD DATA                     →  FLAGGED (not silently dropped)
  ──────────────────────────────────────────────────
  "Springfield" (bad county)   →  flag: UNRECOGNIZED_COUNTY
  "1800" (bad year)            →  flag: INVALID_YEAR
  "Rice" (non-numeric value)   →  flag: NON_NUMERIC_VALUE
  "" (empty county)            →  flag: EMPTY_COUNTY

Run:
    cd backend
    pytest tests/test_cleaning.py -v

See also:
    tests/test_normalizer.py — detailed tests for every internal function
    This file focuses on the KEY BEHAVIOURS a newcomer should understand.
"""

import pytest
import pandas as pd

from app.services.normalizer import (
    normalize_county_value,
    normalize_year_value,
    normalize_numeric_value,
    normalize_indicator_name,
    process_sheet_group,
)


# ============================================================
# Helpers
# ============================================================

def make_raw_group(data: dict, dataset: str = "Test Dataset") -> pd.DataFrame:
    """
    Build a DataFrame that looks like one group from raw_combined.csv.

    Every group has three metadata columns followed by data columns.
    This helper keeps individual tests short and readable.
    """
    df = pd.DataFrame(data)
    df.insert(0, "_dataset_name", dataset)
    df.insert(1, "_source_file",  "test.xlsx")
    df.insert(2, "_source_sheet", "Sheet1")
    return df


# ============================================================
# 1. County name standardisation
# ============================================================
# Raw data arrives with inconsistent county names:
#   "nimba", "NIMBA", "G. Bassa", "Grand bassa", etc.
# The cleaner maps all of these to the canonical 15-county list.

class TestCountyStandardisation:

    def test_exact_name_passes_through(self):
        value, flag = normalize_county_value("Nimba")
        assert value == "Nimba"
        assert flag  is None

    def test_lowercase_is_corrected(self):
        value, flag = normalize_county_value("nimba")
        assert value == "Nimba"    # capital N
        assert flag  is None

    def test_uppercase_is_corrected(self):
        value, flag = normalize_county_value("MONTSERRADO")
        assert value == "Montserrado"
        assert flag  is None

    def test_common_abbreviation_resolved(self):
        # "G. Bassa" is a recognised alias for "Grand Bassa"
        value, flag = normalize_county_value("G. Bassa")
        assert value == "Grand Bassa"
        assert flag  is None

    def test_national_aggregate_accepted(self):
        # "National" rows hold country-level totals — valid
        value, flag = normalize_county_value("National")
        assert value == "National"
        assert flag  is None

    def test_unrecognised_name_is_flagged(self):
        # The cleaner does NOT silently drop bad rows — it flags them
        value, flag = normalize_county_value("Springfield")
        assert value is None
        assert flag  == "UNRECOGNIZED_COUNTY"

    def test_empty_string_is_flagged(self):
        value, flag = normalize_county_value("")
        assert value is None
        assert flag  == "EMPTY_COUNTY"

    def test_nan_string_is_flagged(self):
        # pandas often reads missing cells as the string "nan"
        value, flag = normalize_county_value("nan")
        assert value is None
        assert flag  == "EMPTY_COUNTY"


# ============================================================
# 2. Year value standardisation
# ============================================================
# Years arrive in many formats: "2008", "2016.0", "Survey 2022".
# The cleaner extracts a valid 4-digit year integer or flags the row.

class TestYearStandardisation:

    def test_clean_year_string(self):
        value, flag = normalize_year_value("2008")
        assert value == 2008
        assert isinstance(value, int)
        assert flag  is None

    def test_float_string_becomes_int(self):
        # Excel often exports years as "2016.0"
        value, flag = normalize_year_value("2016.0")
        assert value == 2016
        assert flag  is None

    def test_year_embedded_in_text(self):
        # "Survey 2022" → extracts 2022
        value, flag = normalize_year_value("Survey 2022")
        assert value == 2022
        assert flag  is None

    def test_year_out_of_range_flagged(self):
        # 1800 is outside the 1970–2035 window
        value, flag = normalize_year_value("1800")
        assert value is None
        assert flag  == "INVALID_YEAR"

    def test_non_numeric_year_flagged(self):
        value, flag = normalize_year_value("Male")
        assert value is None
        assert flag  == "INVALID_YEAR"

    def test_empty_year_flagged(self):
        value, flag = normalize_year_value("")
        assert value is None
        assert flag  == "EMPTY_YEAR"


# ============================================================
# 3. Numeric value parsing
# ============================================================
# Values come as strings: "1,450,000", "52.3", "", "N/A", "Rice".
# Blank / N/A → None with no flag (missing data is normal).
# Non-numeric text → flag (data problem).

class TestNumericValueParsing:

    def test_integer_string_parsed(self):
        value, flag = normalize_numeric_value("590000")
        assert value == 590_000.0
        assert flag  is None

    def test_float_string_parsed(self):
        value, flag = normalize_numeric_value("52.3")
        assert value == pytest.approx(52.3)
        assert flag  is None

    def test_comma_formatted_number_parsed(self):
        # "1,450,000" is common in exported spreadsheets
        value, flag = normalize_numeric_value("1,450,000")
        assert value == 1_450_000.0
        assert flag  is None

    def test_blank_cell_returns_none_no_flag(self):
        # A blank cell is normal — it is not an error
        value, flag = normalize_numeric_value("")
        assert value is None
        assert flag  is None   # no flag — blank ≠ bad data

    def test_na_string_returns_none_no_flag(self):
        value, flag = normalize_numeric_value("N/A")
        assert value is None
        assert flag  is None

    def test_dash_returns_none_no_flag(self):
        value, flag = normalize_numeric_value("-")
        assert value is None
        assert flag  is None

    def test_text_value_is_flagged(self):
        # "Rice" cannot be a numeric value — this is a data problem
        value, flag = normalize_numeric_value("Rice")
        assert value is None
        assert flag  == "NON_NUMERIC_VALUE"


# ============================================================
# 4. Indicator name cleaning
# ============================================================
# Indicator names arrive with unit suffixes, underscores,
# inconsistent casing.  The cleaner normalises them.

class TestIndicatorNameCleaning:

    def test_clean_name_unchanged(self):
        assert normalize_indicator_name("Total Population") == "Total Population"

    def test_unit_suffix_removed(self):
        # "(%) is a unit annotation — remove it from the name
        result = normalize_indicator_name("Employment Rate (%)")
        assert result == "Employment Rate"

    def test_short_unit_removed(self):
        result = normalize_indicator_name("Production (MT)")
        assert result == "Production"

    def test_underscores_become_spaces(self):
        result = normalize_indicator_name("under5_mortality_rate")
        assert "_" not in result

    def test_first_word_capitalised(self):
        result = normalize_indicator_name("total population")
        assert result[0].isupper()

    def test_all_caps_abbreviation_preserved(self):
        # "HH" means "Household" — must not become "Hh"
        result = normalize_indicator_name("Urban HH Size (%)")
        assert "HH" in result

    def test_already_clean_name_not_changed(self):
        result = normalize_indicator_name("Literacy Rate")
        assert result == "Literacy Rate"


# ============================================================
# 5. Full sheet group processing
# ============================================================
# process_sheet_group() is the heart of the cleaning pipeline.
# It receives one group of raw rows and returns:
#   (clean_rows, flagged_rows)
#
# Clean rows → go to cleaned_observations.csv → loaded into DB
# Flagged rows → go to flagged_rows.csv → reviewed manually

class TestFullCleaningFlow:

    # ── Happy path ──────────────────────────────────────────────────────

    def test_clean_row_has_all_required_fields(self):
        df = make_raw_group({
            "County": ["Nimba"],
            "Year":   ["2022"],
            "Value":  ["72.3"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 1
        assert len(flagged) == 0
        row = clean[0]
        # Every clean row must have these five fields
        assert "dataset_name"   in row
        assert "indicator_name" in row
        assert "county"         in row
        assert "year"           in row
        assert "value"          in row

    def test_county_name_is_normalised_in_output(self):
        df = make_raw_group({
            "District": ["nimba"],   # lowercase, different column name
            "Year":     ["2016"],
            "Rate":     ["49.1"],
        })
        clean, _ = process_sheet_group(df)
        assert clean[0]["county"] == "Nimba"   # canonical capitalisation

    def test_year_is_integer_in_output(self):
        df = make_raw_group({
            "County Name": ["Bong"],
            "Year":        ["2008"],
            "Pop":         ["350000"],
        })
        clean, _ = process_sheet_group(df)
        assert clean[0]["year"] == 2008
        assert isinstance(clean[0]["year"], int)

    def test_wide_layout_melted_correctly(self):
        """
        A WIDE sheet has multiple value columns per row.
        Each value column becomes a separate observation.
        2 counties × 2 value columns = 4 observations.
        """
        df = make_raw_group({
            "County Name":      ["Nimba",  "Bong"],
            "Year":             ["2008",   "2008"],
            "Total Population": ["590000", "350000"],
            "Male Population":  ["295000", "170000"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 4
        assert len(flagged) == 0

    def test_long_layout_processed_correctly(self):
        """
        A LONG sheet has an explicit 'indicator' column.
        Each row becomes one observation with the indicator name preserved.
        """
        df = make_raw_group({
            "County":    ["Nimba",        "Nimba"],
            "Year":      ["2022",         "2022"],
            "indicator": ["Literacy Rate", "Under-5 Mortality"],
            "value":     ["72.3",          "95.0"],
        })
        clean, _ = process_sheet_group(df)
        assert len(clean) == 2
        indicator_names = {row["indicator_name"] for row in clean}
        assert "Literacy Rate" in indicator_names

    def test_blank_value_cell_silently_skipped(self):
        """A blank value is missing data — not an error — so it is skipped, not flagged."""
        df = make_raw_group({
            "County": ["Nimba", "Bong"],
            "Year":   ["2022",  "2022"],
            "Value":  ["72.3",  ""],       # Bong has no data
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 1    # only Nimba
        assert len(flagged) == 0    # blank is not an error

    # ── Flagged rows ────────────────────────────────────────────────────

    def test_bad_county_flagged_not_dropped_silently(self):
        """
        A row with an unrecognised county name must appear in flagged_rows.csv.
        It must NOT silently disappear — that would hide data problems.
        """
        df = make_raw_group({
            "County": ["Springfield"],
            "Year":   ["2022"],
            "Value":  ["100.0"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 0
        assert len(flagged) == 1
        assert flagged[0]["_flag_reason"] == "UNRECOGNIZED_COUNTY"

    def test_invalid_year_flagged(self):
        df = make_raw_group({
            "County": ["Nimba"],
            "Year":   ["not_a_year"],
            "Value":  ["100.0"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 0
        assert len(flagged) == 1
        assert flagged[0]["_flag_reason"] == "INVALID_YEAR"

    def test_non_numeric_value_flagged(self):
        df = make_raw_group({
            "County": ["Nimba"],
            "Year":   ["2022"],
            "Value":  ["See note"],   # text where a number is expected
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 0
        assert len(flagged) == 1
        assert flagged[0]["_flag_reason"] == "NON_NUMERIC_VALUE"

    def test_no_county_column_flags_all_rows(self):
        """
        If the cleaner cannot detect a county column, every row is flagged.
        This prevents silent data loss when the sheet has an unusual structure.
        """
        df = make_raw_group({
            "crop_type":  ["Rice",  "Corn"],
            "year":       ["2019",  "2019"],
            "production": ["500",   "300"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 0
        assert len(flagged) == 2
        assert all(r["_flag_reason"] == "NO_COUNTY_COLUMN" for r in flagged)

    def test_flagged_rows_retain_source_tracing(self):
        """
        Flagged rows keep their _source_file and _source_sheet so that
        the data team can find and fix the original Excel file.
        """
        df = make_raw_group({
            "County": ["InvalidPlace"],
            "Year":   ["2022"],
            "Value":  ["100.0"],
        })
        _, flagged = process_sheet_group(df)
        assert "_source_file"  in flagged[0]
        assert "_source_sheet" in flagged[0]
        assert "_flag_reason"  in flagged[0]

    def test_mixed_valid_and_invalid_rows_split_correctly(self):
        """
        In the same sheet, good rows go to clean and bad rows go to flagged.
        The cleaner handles each row independently.
        """
        df = make_raw_group({
            "County": ["Nimba",       "FakeCounty"],
            "Year":   ["2022",        "2022"],
            "Value":  ["72.3",        "50.0"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean)   == 1
        assert len(flagged) == 1
        assert clean[0]["county"]         == "Nimba"
        assert flagged[0]["_flag_reason"] == "UNRECOGNIZED_COUNTY"
