"""
backend/tests/test_ingestion.py
=================================
Unit tests for the ingestion service.

These tests use temporary files and directories — no real Excel files needed.
Each test is small and tests exactly one function.

Run:
    cd backend
    pytest tests/test_ingestion.py -v
"""

import pytest
import pandas as pd
from pathlib import Path

# All functions tested individually
from app.services.ingestion import (
    discover_excel_files,
    derive_dataset_name,
    load_sheet,
    load_excel_file,
    combine_dataframes,
    DATASET_NAME_OVERRIDES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_raw_dir(tmp_path):
    """Return a fresh temporary directory (empty, like a new data/raw/)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    return raw


@pytest.fixture
def sample_excel_single_sheet(tmp_path):
    """
    Create a minimal single-sheet Excel file for testing.
    Columns: County, Year, Value
    """
    path = tmp_path / "Population_Survey_2022.xlsx"
    df = pd.DataFrame({
        "County": ["Montserrado", "Nimba", "Bong"],
        "Year":   [2022, 2022, 2022],
        "Value":  [1500000, 590000, 350000],
    })
    df.to_excel(path, index=False, sheet_name="Data")
    return path


@pytest.fixture
def sample_excel_multi_sheet(tmp_path):
    """
    Create an Excel file with two sheets that have DIFFERENT columns.
    This tests the core design constraint: no assumed consistency.
    """
    path = tmp_path / "Census_2008.xlsx"
    df_pop = pd.DataFrame({
        "County Name":       ["Bomi", "Bong"],
        "Total Population":  [100000, 350000],
        "Year":              [2008, 2008],
    })
    df_hh = pd.DataFrame({
        # Completely different columns — intentional
        "District":          ["Bomi", "Bong"],
        "Households":        [20000, 70000],
        "Survey Year":       [2008, 2008],
    })
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_pop.to_excel(writer, sheet_name="Population",  index=False)
        df_hh.to_excel( writer, sheet_name="Households", index=False)
    return path


# ---------------------------------------------------------------------------
# Tests: discover_excel_files
# ---------------------------------------------------------------------------

class TestDiscoverExcelFiles:

    def test_finds_xlsx_files(self, tmp_raw_dir, sample_excel_single_sheet):
        # Copy file into raw dir
        dest = tmp_raw_dir / sample_excel_single_sheet.name
        dest.write_bytes(sample_excel_single_sheet.read_bytes())

        result = discover_excel_files(tmp_raw_dir)
        assert len(result) == 1
        assert result[0].name == sample_excel_single_sheet.name

    def test_returns_empty_for_empty_directory(self, tmp_raw_dir):
        result = discover_excel_files(tmp_raw_dir)
        assert result == []

    def test_ignores_non_excel_files(self, tmp_raw_dir):
        (tmp_raw_dir / "notes.txt").write_text("not an excel file")
        (tmp_raw_dir / "data.csv").write_text("a,b\n1,2")
        result = discover_excel_files(tmp_raw_dir)
        assert result == []

    def test_ignores_temp_excel_files(self, tmp_raw_dir):
        # Excel creates ~$filename.xlsx temp files while a file is open
        (tmp_raw_dir / "~$Population.xlsx").write_bytes(b"garbage")
        result = discover_excel_files(tmp_raw_dir)
        assert result == []

    def test_returns_empty_for_nonexistent_directory(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = discover_excel_files(nonexistent)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: derive_dataset_name
# ---------------------------------------------------------------------------

class TestDeriveDatasetName:

    def test_underscores_become_spaces(self, tmp_path):
        path = tmp_path / "LISGIS_Census_2008.xlsx"
        result = derive_dataset_name(path)
        assert "_" not in result

    def test_hyphens_become_spaces(self, tmp_path):
        path = tmp_path / "Employment-Survey-2016.xlsx"
        result = derive_dataset_name(path)
        assert "-" not in result

    def test_output_is_title_case(self, tmp_path):
        path = tmp_path / "health_indicators_2020.xlsx"
        result = derive_dataset_name(path)
        words = result.split()
        assert all(w[0].isupper() for w in words if w[0].isalpha())

    def test_extension_is_not_included(self, tmp_path):
        path = tmp_path / "Population_Survey.xlsx"
        result = derive_dataset_name(path)
        assert ".xlsx" not in result
        assert ".xls" not in result

    def test_override_takes_priority(self, tmp_path, monkeypatch):
        # Temporarily add an override
        monkeypatch.setitem(
            DATASET_NAME_OVERRIDES,
            "cryptic_export_v3",
            "Household Income Survey 2022",
        )
        path = tmp_path / "cryptic_export_v3.xlsx"
        result = derive_dataset_name(path)
        assert result == "Household Income Survey 2022"

    def test_multiple_separators(self, tmp_path):
        path = tmp_path / "data__with---multiple___separators.xlsx"
        result = derive_dataset_name(path)
        # Should not have double spaces
        assert "  " not in result


# ---------------------------------------------------------------------------
# Tests: load_sheet
# ---------------------------------------------------------------------------

class TestLoadSheet:

    def test_metadata_columns_are_present(self, sample_excel_single_sheet):
        df = load_sheet(sample_excel_single_sheet, "Data", "Test Dataset")
        assert "_dataset_name" in df.columns
        assert "_source_file"  in df.columns
        assert "_source_sheet" in df.columns

    def test_metadata_values_are_correct(self, sample_excel_single_sheet):
        df = load_sheet(sample_excel_single_sheet, "Data", "Test Dataset")
        assert df["_dataset_name"].iloc[0] == "Test Dataset"
        assert df["_source_file"].iloc[0]  == sample_excel_single_sheet.name
        assert df["_source_sheet"].iloc[0] == "Data"

    def test_metadata_columns_come_first(self, sample_excel_single_sheet):
        df = load_sheet(sample_excel_single_sheet, "Data", "Test Dataset")
        assert list(df.columns[:3]) == ["_dataset_name", "_source_file", "_source_sheet"]

    def test_original_rows_preserved(self, sample_excel_single_sheet):
        df = load_sheet(sample_excel_single_sheet, "Data", "Test Dataset")
        assert len(df) == 3  # 3 counties in fixture

    def test_returns_none_for_bad_sheet_name(self, sample_excel_single_sheet):
        result = load_sheet(sample_excel_single_sheet, "NonExistentSheet", "Test")
        assert result is None

    def test_all_values_are_strings(self, sample_excel_single_sheet):
        df = load_sheet(sample_excel_single_sheet, "Data", "Test Dataset")
        # Exclude metadata columns which are already strings
        data_cols = [c for c in df.columns if not c.startswith("_")]
        for col in data_cols:
            assert df[col].dtype == object  # object dtype = string in pandas


# ---------------------------------------------------------------------------
# Tests: load_excel_file
# ---------------------------------------------------------------------------

class TestLoadExcelFile:

    def test_returns_one_df_per_sheet(self, sample_excel_multi_sheet):
        result = load_excel_file(sample_excel_multi_sheet)
        assert len(result) == 2  # two sheets

    def test_each_df_has_metadata(self, sample_excel_multi_sheet):
        result = load_excel_file(sample_excel_multi_sheet)
        for df in result:
            assert "_dataset_name" in df.columns
            assert "_source_file"  in df.columns
            assert "_source_sheet" in df.columns

    def test_sheets_have_different_columns(self, sample_excel_multi_sheet):
        result = load_excel_file(sample_excel_multi_sheet)
        cols_sheet1 = set(result[0].columns)
        cols_sheet2 = set(result[1].columns)
        # The data columns should be different (that's the whole point)
        data_cols1 = cols_sheet1 - {"_dataset_name", "_source_file", "_source_sheet"}
        data_cols2 = cols_sheet2 - {"_dataset_name", "_source_file", "_source_sheet"}
        assert data_cols1 != data_cols2

    def test_returns_empty_list_for_nonexistent_file(self, tmp_path):
        fake = tmp_path / "doesnotexist.xlsx"
        result = load_excel_file(fake)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: combine_dataframes
# ---------------------------------------------------------------------------

class TestCombineDataframes:

    def test_combines_rows(self):
        df1 = pd.DataFrame({"_dataset_name": ["A"], "_source_file": ["a.xlsx"], "_source_sheet": ["s1"], "county": ["Nimba"]})
        df2 = pd.DataFrame({"_dataset_name": ["B"], "_source_file": ["b.xlsx"], "_source_sheet": ["s1"], "county": ["Bong"]})
        result = combine_dataframes([df1, df2])
        assert len(result) == 2

    def test_columns_are_union_of_all_columns(self):
        df1 = pd.DataFrame({"_dataset_name": ["A"], "_source_file": ["a.xlsx"], "_source_sheet": ["s"], "population": [100]})
        df2 = pd.DataFrame({"_dataset_name": ["B"], "_source_file": ["b.xlsx"], "_source_sheet": ["s"], "employment_rate": [55.0]})
        result = combine_dataframes([df1, df2])
        # Both columns must be present
        assert "population"      in result.columns
        assert "employment_rate" in result.columns

    def test_missing_columns_filled_with_nan(self):
        df1 = pd.DataFrame({"_dataset_name": ["A"], "_source_file": ["a.xlsx"], "_source_sheet": ["s"], "population": [100]})
        df2 = pd.DataFrame({"_dataset_name": ["B"], "_source_file": ["b.xlsx"], "_source_sheet": ["s"], "employment_rate": [55.0]})
        result = combine_dataframes([df1, df2])
        # Row from df1 should have NaN for employment_rate
        row_a = result[result["_dataset_name"] == "A"].iloc[0]
        assert pd.isna(row_a["employment_rate"])

    def test_raises_on_empty_input(self):
        with pytest.raises(ValueError, match="No data to combine"):
            combine_dataframes([])

    def test_index_is_reset(self):
        df1 = pd.DataFrame({"_dataset_name": ["A"], "_source_file": ["a.xlsx"], "_source_sheet": ["s"], "x": [1]})
        df2 = pd.DataFrame({"_dataset_name": ["B"], "_source_file": ["b.xlsx"], "_source_sheet": ["s"], "x": [2]})
        result = combine_dataframes([df1, df2])
        assert list(result.index) == [0, 1]


# ---------------------------------------------------------------------------
# Integration test: full pipeline on temp files
# ---------------------------------------------------------------------------

class TestRunIngestion:

    def test_end_to_end(self, tmp_path, sample_excel_single_sheet, sample_excel_multi_sheet):
        """Full pipeline: two files → combined CSV."""
        from app.services.ingestion import run_ingestion

        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        output  = tmp_path / "processed" / "raw_combined.csv"

        # Copy both sample files into raw_dir
        (raw_dir / sample_excel_single_sheet.name).write_bytes(
            sample_excel_single_sheet.read_bytes()
        )
        (raw_dir / sample_excel_multi_sheet.name).write_bytes(
            sample_excel_multi_sheet.read_bytes()
        )

        summary = run_ingestion(raw_dir=raw_dir, output_path=output)

        assert summary["files_found"]   == 2
        assert summary["files_loaded"]  == 2
        assert summary["sheets_loaded"] == 3   # 1 + 2 sheets
        assert summary["total_rows"]    >  0
        assert output.exists()

        # Verify the output CSV has the metadata columns
        result_df = pd.read_csv(output)
        assert "_dataset_name" in result_df.columns
        assert "_source_file"  in result_df.columns
        assert "_source_sheet" in result_df.columns

    def test_empty_raw_dir_returns_zero_counts(self, tmp_path):
        from app.services.ingestion import run_ingestion

        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        output = tmp_path / "out.csv"

        summary = run_ingestion(raw_dir=raw_dir, output_path=output)

        assert summary["files_found"]  == 0
        assert summary["total_rows"]   == 0
        assert not output.exists()
