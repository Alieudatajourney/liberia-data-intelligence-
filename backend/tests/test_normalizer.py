"""
backend/tests/test_normalizer.py
==================================
Unit tests for the normalization service.

Each test class covers one function.
Tests use small hand-crafted DataFrames — no file I/O needed.

Run:
    cd backend
    pytest tests/test_normalizer.py -v
"""

import pytest
import pandas as pd
from pathlib import Path

from app.services.normalizer import (
    # Scoring helpers
    _name_score,
    _county_value_score,
    _year_value_score,
    _numeric_value_score,
    # Column detection
    detect_county_column,
    detect_year_column,
    detect_indicator_column,
    detect_value_columns,
    # Value normalization
    normalize_county_value,
    normalize_year_value,
    normalize_numeric_value,
    normalize_indicator_name,
    # Group processor
    process_sheet_group,
    # Orchestrator
    run_normalization,
)


# ===========================================================================
# Helpers
# ===========================================================================

def make_group_df(data: dict, file: str = "test.xlsx", sheet: str = "Sheet1") -> pd.DataFrame:
    """
    Build a minimal DataFrame that looks like a group from raw_combined.csv.
    Adds the required _metadata columns.
    """
    df = pd.DataFrame(data)
    df.insert(0, "_dataset_name", "Test Dataset")
    df.insert(1, "_source_file",  file)
    df.insert(2, "_source_sheet", sheet)
    return df


# ===========================================================================
# Scoring helpers
# ===========================================================================

class TestNameScore:

    def test_exact_match_scores_one(self):
        assert _name_score("county", ["county"]) == 1.0

    def test_starts_with_hint_scores_high(self):
        assert _name_score("county name", ["county"]) >= 0.80

    def test_hint_is_substring_scores_medium(self):
        assert _name_score("the county name", ["county"]) >= 0.50

    def test_no_match_scores_zero(self):
        assert _name_score("population", ["county", "district"]) == 0.0

    def test_case_insensitive(self):
        assert _name_score("COUNTY", ["county"]) > 0.0

    def test_underscore_treated_as_space(self):
        assert _name_score("reference_year", ["year"]) > 0.0


class TestCountyValueScore:

    def test_all_counties_score_one(self):
        s = pd.Series(["Montserrado", "Nimba", "Bong"])
        assert _county_value_score(s) == 1.0

    def test_no_counties_score_zero(self):
        s = pd.Series(["Apple", "Banana", "Cherry"])
        assert _county_value_score(s) == 0.0

    def test_empty_series_score_zero(self):
        assert _county_value_score(pd.Series([])) == 0.0

    def test_partial_match_scores_fraction(self):
        s = pd.Series(["Nimba", "Nimba", "NotACounty"])
        score = _county_value_score(s)
        assert 0.0 < score < 1.0


class TestYearValueScore:

    def test_all_years_score_one(self):
        s = pd.Series(["2008", "2016", "2022"])
        assert _year_value_score(s) == 1.0

    def test_non_years_score_zero(self):
        s = pd.Series(["Male", "Female", "Both"])
        assert _year_value_score(s) == 0.0

    def test_out_of_range_scores_zero(self):
        s = pd.Series(["1800", "2500", "9999"])
        assert _year_value_score(s) == 0.0


class TestNumericValueScore:

    def test_all_numeric_score_one(self):
        s = pd.Series(["1234", "56.7", "0.0"])
        assert _numeric_value_score(s) == 1.0

    def test_all_text_score_zero(self):
        s = pd.Series(["Rice", "Cassava", "Coffee"])
        assert _numeric_value_score(s) == 0.0

    def test_na_strings_excluded_from_scoring(self):
        # "N/A" and "-" should be excluded before scoring, not counted as failures
        s = pd.Series(["52.3", "N/A", "-", "48.1"])
        score = _numeric_value_score(s)
        assert score == 1.0  # 2/2 non-missing values are numeric

    def test_comma_separated_numbers_score_high(self):
        s = pd.Series(["1,234", "56,789"])
        assert _numeric_value_score(s) == 1.0


# ===========================================================================
# Column detection
# ===========================================================================

class TestDetectCountyColumn:

    def test_detects_county_name_column(self):
        df = pd.DataFrame({"County Name": ["Nimba", "Bong"], "Value": [1, 2]})
        assert detect_county_column(df) == "County Name"

    def test_detects_district_column(self):
        df = pd.DataFrame({"District": ["Nimba", "Bong"], "Year": [2016, 2016]})
        assert detect_county_column(df) == "District"

    def test_detects_location_column_by_values(self):
        # "location" is a weak name hint, but values are all counties → detected
        df = pd.DataFrame({"location": ["Montserrado", "Lofa"], "ref_year": [2020, 2020]})
        assert detect_county_column(df) == "location"

    def test_returns_none_when_no_county_column(self):
        df = pd.DataFrame({"crop_type": ["Rice", "Corn"], "production": [100, 200]})
        assert detect_county_column(df) is None


class TestDetectYearColumn:

    def test_detects_year_column(self):
        df = pd.DataFrame({"County": ["Nimba"], "Year": ["2008"], "Pop": ["100"]})
        result = detect_year_column(df, exclude=["County"])
        assert result == "Year"

    def test_detects_survey_year(self):
        df = pd.DataFrame({"District": ["Bong"], "Survey Year": ["2016"], "Rate": ["55.0"]})
        result = detect_year_column(df, exclude=["District"])
        assert result == "Survey Year"

    def test_detects_reference_year(self):
        df = pd.DataFrame({"location": ["Nimba"], "reference_year": ["2020"], "rate": ["30.0"]})
        result = detect_year_column(df, exclude=["location"])
        assert result == "reference_year"

    def test_returns_none_when_no_year_column(self):
        df = pd.DataFrame({"County": ["Nimba"], "Indicator": ["Pop"], "Value": ["100"]})
        result = detect_year_column(df, exclude=["County"])
        assert result is None


class TestDetectIndicatorColumn:

    def test_detects_indicator_column(self):
        df = pd.DataFrame({
            "County": ["Nimba"], "Year": ["2022"],
            "indicator": ["Literacy Rate"], "value": ["72.3"]
        })
        result = detect_indicator_column(df, exclude=["County", "Year"])
        assert result == "indicator"

    def test_returns_none_when_no_indicator_column(self):
        df = pd.DataFrame({
            "County": ["Nimba"], "Year": ["2022"],
            "Total Population": ["100000"], "Male Pop": ["50000"],
        })
        result = detect_indicator_column(df, exclude=["County", "Year"])
        assert result is None


class TestDetectValueColumns:

    def test_detects_numeric_columns(self):
        df = pd.DataFrame({
            "County": ["Nimba", "Bong"],
            "Year":   ["2022", "2022"],
            "Total Population": ["100000", "350000"],
            "Male Population":  ["50000",  "170000"],
        })
        result = detect_value_columns(df, exclude=["County", "Year"])
        assert "Total Population" in result
        assert "Male Population" in result

    def test_excludes_text_columns(self):
        df = pd.DataFrame({
            "County": ["Nimba"],
            "Year":   ["2022"],
            "Notes":  ["Some note"],
            "Value":  ["100.0"],
        })
        result = detect_value_columns(df, exclude=["County", "Year"])
        assert "Notes" not in result
        assert "Value" in result

    def test_excludes_string_columns(self):
        # "Gender" has string values — must not be treated as a value column
        df = pd.DataFrame({
            "District":             ["Bomi", "Bomi"],
            "Survey Year":          ["2016", "2016"],
            "Gender":               ["Male", "Female"],
            "Employment Rate (%)":  ["52.3", "48.1"],
        })
        result = detect_value_columns(df, exclude=["District", "Survey Year"])
        assert "Gender" not in result
        assert "Employment Rate (%)" in result

    def test_excludes_explicitly_excluded_columns(self):
        df = pd.DataFrame({
            "County": ["Nimba"],
            "Year":   ["2022"],
            "Pop":    ["100000"],
        })
        result = detect_value_columns(df, exclude=["County", "Year", "Pop"])
        assert "Pop" not in result


# ===========================================================================
# Value normalization
# ===========================================================================

class TestNormalizeCountyValue:

    def test_exact_match(self):
        val, flag = normalize_county_value("Montserrado")
        assert val == "Montserrado"
        assert flag is None

    def test_lowercase_match(self):
        val, flag = normalize_county_value("nimba")
        assert val == "Nimba"
        assert flag is None

    def test_alias_match(self):
        val, flag = normalize_county_value("G. Bassa")
        assert val == "Grand Bassa"
        assert flag is None

    def test_national_accepted(self):
        val, flag = normalize_county_value("National")
        assert val == "National"
        assert flag is None

    def test_unknown_county_flagged(self):
        val, flag = normalize_county_value("Springfield")
        assert val is None
        assert flag == "UNRECOGNIZED_COUNTY"

    def test_empty_value_flagged(self):
        val, flag = normalize_county_value("")
        assert val is None
        assert flag == "EMPTY_COUNTY"

    def test_nan_string_flagged(self):
        val, flag = normalize_county_value("nan")
        assert val is None
        assert flag == "EMPTY_COUNTY"


class TestNormalizeYearValue:

    def test_valid_year(self):
        val, flag = normalize_year_value("2008")
        assert val == 2008
        assert flag is None

    def test_float_string_year(self):
        val, flag = normalize_year_value("2016.0")
        assert val == 2016
        assert flag is None

    def test_year_embedded_in_string(self):
        val, flag = normalize_year_value("Survey 2022")
        assert val == 2022
        assert flag is None

    def test_out_of_range_year_flagged(self):
        _, flag = normalize_year_value("1800")
        assert flag == "INVALID_YEAR"

    def test_empty_string_flagged(self):
        _, flag = normalize_year_value("")
        assert flag == "EMPTY_YEAR"

    def test_non_year_text_flagged(self):
        _, flag = normalize_year_value("Male")
        assert flag == "INVALID_YEAR"


class TestNormalizeNumericValue:

    def test_integer_string(self):
        val, flag = normalize_numeric_value("1450000")
        assert val == 1450000.0
        assert flag is None

    def test_float_string(self):
        val, flag = normalize_numeric_value("52.3")
        assert val == 52.3
        assert flag is None

    def test_comma_separated(self):
        val, flag = normalize_numeric_value("1,450,000")
        assert val == 1450000.0
        assert flag is None

    def test_blank_returns_none_no_flag(self):
        val, flag = normalize_numeric_value("")
        assert val is None
        assert flag is None  # blank is not an error

    def test_na_string_returns_none_no_flag(self):
        val, flag = normalize_numeric_value("N/A")
        assert val is None
        assert flag is None

    def test_non_numeric_string_flagged(self):
        val, flag = normalize_numeric_value("Rice")
        assert val is None
        assert flag == "NON_NUMERIC_VALUE"


class TestNormalizeIndicatorName:

    def test_clean_name_unchanged(self):
        assert normalize_indicator_name("Total Population") == "Total Population"

    def test_unit_suffix_stripped(self):
        assert normalize_indicator_name("Employment Rate (%)") == "Employment Rate"

    def test_short_unit_stripped(self):
        assert normalize_indicator_name("Production (MT)") == "Production"

    def test_underscore_becomes_space(self):
        result = normalize_indicator_name("under5_mortality_rate")
        assert "_" not in result

    def test_lowercase_title_cased(self):
        result = normalize_indicator_name("under5 mortality rate")
        assert result[0].isupper()

    def test_all_caps_preserved(self):
        # "HH" is an abbreviation — should not become "Hh"
        result = normalize_indicator_name("Urban HH (%)")
        assert "HH" in result

    def test_mixed_case_preserved(self):
        result = normalize_indicator_name("Employment Rate")
        assert result == "Employment Rate"


# ===========================================================================
# process_sheet_group
# ===========================================================================

class TestProcessSheetGroup:

    def test_wide_layout_produces_one_obs_per_value_col(self):
        df = make_group_df({
            "County Name": ["Nimba", "Bong"],
            "Year":        ["2008", "2008"],
            "Total Pop":   ["100000", "350000"],
            "Male Pop":    ["50000",  "170000"],
        })
        clean, flagged = process_sheet_group(df)
        # 2 counties × 2 value cols = 4 observations
        assert len(clean) == 4
        assert len(flagged) == 0

    def test_clean_rows_have_correct_keys(self):
        df = make_group_df({
            "County": ["Nimba"],
            "Year":   ["2022"],
            "Value":  ["72.3"],
        })
        clean, _ = process_sheet_group(df)
        assert len(clean) == 1
        row = clean[0]
        assert set(row.keys()) >= {"dataset_name", "indicator_name", "county", "year", "value"}

    def test_county_is_normalized(self):
        df = make_group_df({
            "District": ["nimba"],
            "Year":     ["2016"],
            "Rate":     ["52.3"],
        })
        clean, _ = process_sheet_group(df)
        assert clean[0]["county"] == "Nimba"

    def test_year_is_integer(self):
        df = make_group_df({
            "County Name": ["Bong"],
            "Year":        ["2008"],
            "Pop":         ["350000"],
        })
        clean, _ = process_sheet_group(df)
        assert clean[0]["year"] == 2008
        assert isinstance(clean[0]["year"], int)

    def test_blank_value_cells_silently_skipped(self):
        df = make_group_df({
            "County": ["Nimba", "Bong"],
            "Year":   ["2022",  "2022"],
            "Value":  ["72.3",  ""],    # Bong has blank
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean) == 1   # only Nimba
        assert len(flagged) == 0  # blank is not an error

    def test_unrecognized_county_flagged(self):
        df = make_group_df({
            "County": ["InvalidPlace"],
            "Year":   ["2022"],
            "Value":  ["100.0"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean) == 0
        assert len(flagged) == 1
        assert flagged[0]["_flag_reason"] == "UNRECOGNIZED_COUNTY"

    def test_invalid_year_flagged(self):
        df = make_group_df({
            "County": ["Nimba"],
            "Year":   ["not_a_year"],
            "Value":  ["100.0"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean) == 0
        assert len(flagged) == 1
        assert flagged[0]["_flag_reason"] == "INVALID_YEAR"

    def test_no_county_column_flags_all_rows(self):
        df = make_group_df({
            "crop_type": ["Rice", "Corn"],
            "year":      ["2019", "2019"],
            "production": ["500", "300"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean) == 0
        assert len(flagged) == 2
        assert all(r["_flag_reason"] == "NO_COUNTY_COLUMN" for r in flagged)

    def test_long_layout_detected_when_indicator_column_present(self):
        df = make_group_df({
            "County":    ["Nimba", "Nimba"],
            "Year":      ["2022",  "2022"],
            "indicator": ["Literacy Rate", "Under-5 Mortality"],
            "value":     ["72.3",  "95.0"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean) == 2
        assert {r["indicator_name"] for r in clean} == {"Literacy Rate", "Under 5 Mortality"}

    def test_source_tracing_preserved_in_clean_rows(self):
        df = make_group_df(
            {"County": ["Bong"], "Year": ["2022"], "Value": ["1.0"]},
            file="census.xlsx", sheet="Population"
        )
        clean, _ = process_sheet_group(df)
        assert clean[0]["_source_file"]  == "census.xlsx"
        assert clean[0]["_source_sheet"] == "Population"

    def test_non_numeric_value_flagged(self):
        df = make_group_df({
            "County": ["Nimba"],
            "Year":   ["2022"],
            "Value":  ["NotANumber"],
        })
        clean, flagged = process_sheet_group(df)
        assert len(clean) == 0
        assert len(flagged) == 1
        assert flagged[0]["_flag_reason"] == "NON_NUMERIC_VALUE"


# ===========================================================================
# run_normalization (integration)
# ===========================================================================

class TestRunNormalization:

    def _make_raw_csv(self, tmp_path: Path) -> Path:
        """Write a minimal raw_combined.csv for integration testing."""
        raw_path = tmp_path / "raw_combined.csv"
        rows = [
            {
                "_dataset_name": "Test Dataset",
                "_source_file":  "census.xlsx",
                "_source_sheet": "Population",
                "County Name": "Montserrado",
                "Year":        "2008",
                "Total Pop":   "1450000",
                # These come from other sheets — NaN for this group
                "District": float("nan"),
                "Survey Year": float("nan"),
                "Employment Rate (%)": float("nan"),
            },
            {
                "_dataset_name": "Test Dataset 2",
                "_source_file":  "employment.xlsx",
                "_source_sheet": "Employment Data",
                "County Name":   float("nan"),
                "Year":          float("nan"),
                "Total Pop":     float("nan"),
                "District":      "Nimba",
                "Survey Year":   "2016",
                "Employment Rate (%)": "52.3",
            },
        ]
        pd.DataFrame(rows).to_csv(raw_path, index=False)
        return raw_path

    def test_produces_clean_and_flagged_files(self, tmp_path):
        raw_path   = self._make_raw_csv(tmp_path)
        output_dir = tmp_path / "processed"

        summary = run_normalization(input_path=raw_path, output_dir=output_dir)

        assert (output_dir / "cleaned_observations.csv").exists()
        assert (output_dir / "flagged_rows.csv").exists()
        assert summary["clean_observations"] > 0

    def test_clean_output_has_correct_columns(self, tmp_path):
        raw_path   = self._make_raw_csv(tmp_path)
        output_dir = tmp_path / "processed"

        run_normalization(input_path=raw_path, output_dir=output_dir)

        df = pd.read_csv(output_dir / "cleaned_observations.csv")
        required_cols = {"dataset_name", "indicator_name", "county", "year", "value"}
        assert required_cols.issubset(set(df.columns))

    def test_raises_on_missing_input(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            run_normalization(
                input_path = tmp_path / "nonexistent.csv",
                output_dir = tmp_path / "out",
            )

    def test_groups_are_processed_independently(self, tmp_path):
        """
        Key design test: two groups with different column names must both normalize.
        """
        raw_path   = self._make_raw_csv(tmp_path)
        output_dir = tmp_path / "processed"

        summary = run_normalization(input_path=raw_path, output_dir=output_dir)

        # Both groups should contribute clean rows
        assert summary["groups_processed"] == 2
        assert summary["clean_observations"] >= 2
