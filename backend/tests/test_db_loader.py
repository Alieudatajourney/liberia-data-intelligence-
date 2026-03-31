"""
backend/tests/test_db_loader.py
=================================
Tests for the database loading service.

Uses an in-memory SQLite database — no PostgreSQL required.
SQLite shares the same SQLAlchemy interface, so the ORM code
runs identically. Tests are fully isolated: each test gets
a fresh empty database.

Run:
    cd backend
    pytest tests/test_db_loader.py -v
"""

import pytest
import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Dataset, Indicator, County, Observation
from app.services.db_loader_service import (
    get_or_create_dataset,
    get_or_create_indicator,
    get_or_create_county,
    load_dimensions,
    load_observations,
    run_db_load,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def db():
    """
    Provide a clean in-memory SQLite session for each test.

    SQLite does not enforce foreign keys by default.
    The event listener below enables FK enforcement so tests
    behave closer to PostgreSQL.
    """
    sqlite_engine = create_engine("sqlite:///:memory:", echo=False)

    # Enable FK enforcement in SQLite
    @event.listens_for(sqlite_engine, "connect")
    def set_sqlite_pragma(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    # Create all tables in the in-memory DB
    Base.metadata.create_all(bind=sqlite_engine)

    Session = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=sqlite_engine)


@pytest.fixture
def sample_df():
    """
    A minimal cleaned_observations DataFrame with two datasets,
    multiple indicators, and multiple counties.
    """
    return pd.DataFrame([
        # Dataset A — Census
        {"dataset_name": "Lisgis Census 2008", "indicator_name": "Total Population",
         "county": "Montserrado", "year": "2008", "value": "1450000"},
        {"dataset_name": "Lisgis Census 2008", "indicator_name": "Total Population",
         "county": "Nimba",       "year": "2008", "value": "590000"},
        {"dataset_name": "Lisgis Census 2008", "indicator_name": "Male Population",
         "county": "Montserrado", "year": "2008", "value": "725000"},
        # Dataset B — Employment
        {"dataset_name": "Employment Survey 2016", "indicator_name": "Employment Rate",
         "county": "Montserrado", "year": "2016", "value": "58.3"},
        {"dataset_name": "Employment Survey 2016", "indicator_name": "Employment Rate",
         "county": "Nimba",       "year": "2016", "value": "49.1"},
    ])


# ===========================================================================
# get_or_create_dataset
# ===========================================================================

class TestGetOrCreateDataset:

    def test_creates_new_dataset(self, db):
        cache = {}
        dataset_id = get_or_create_dataset(db, "Census 2008", cache)
        assert isinstance(dataset_id, int)
        assert dataset_id > 0

    def test_returns_same_id_on_second_call(self, db):
        cache = {}
        id1 = get_or_create_dataset(db, "Census 2008", cache)
        id2 = get_or_create_dataset(db, "Census 2008", cache)
        assert id1 == id2

    def test_cache_populated_after_creation(self, db):
        cache = {}
        dataset_id = get_or_create_dataset(db, "Census 2008", cache)
        assert "Census 2008" in cache
        assert cache["Census 2008"] == dataset_id

    def test_cache_hit_does_not_query_db(self, db):
        cache = {"Census 2008": 999}  # pre-populated with a fake id
        result = get_or_create_dataset(db, "Census 2008", cache)
        # Must return the cached value, not hit the DB
        assert result == 999

    def test_different_names_get_different_ids(self, db):
        cache = {}
        id1 = get_or_create_dataset(db, "Dataset A", cache)
        id2 = get_or_create_dataset(db, "Dataset B", cache)
        assert id1 != id2

    def test_existing_db_row_reused(self, db):
        # Insert a row directly into the DB
        ds = Dataset(name="Pre-existing Dataset")
        db.add(ds)
        db.commit()
        preexisting_id = ds.id

        # Now ask get_or_create — it should find the existing row
        cache = {}
        result = get_or_create_dataset(db, "Pre-existing Dataset", cache)
        assert result == preexisting_id


# ===========================================================================
# get_or_create_indicator
# ===========================================================================

class TestGetOrCreateIndicator:

    def test_creates_new_indicator(self, db):
        cache_d, cache_i = {}, {}
        ds_id = get_or_create_dataset(db, "DS", cache_d)
        db.commit()
        ind_id = get_or_create_indicator(db, "Total Population", ds_id, cache_i)
        assert isinstance(ind_id, int)

    def test_same_name_different_dataset_gets_different_id(self, db):
        cache_d, cache_i = {}, {}
        ds_id_1 = get_or_create_dataset(db, "Dataset 1", cache_d)
        ds_id_2 = get_or_create_dataset(db, "Dataset 2", cache_d)
        db.commit()

        id1 = get_or_create_indicator(db, "Total Population", ds_id_1, cache_i)
        id2 = get_or_create_indicator(db, "Total Population", ds_id_2, cache_i)
        assert id1 != id2

    def test_same_name_same_dataset_returns_same_id(self, db):
        cache_d, cache_i = {}, {}
        ds_id = get_or_create_dataset(db, "DS", cache_d)
        db.commit()
        id1 = get_or_create_indicator(db, "Total Population", ds_id, cache_i)
        id2 = get_or_create_indicator(db, "Total Population", ds_id, cache_i)
        assert id1 == id2


# ===========================================================================
# get_or_create_county
# ===========================================================================

class TestGetOrCreateCounty:

    def test_creates_new_county(self, db):
        cache = {}
        county_id = get_or_create_county(db, "Montserrado", cache)
        assert isinstance(county_id, int)

    def test_global_not_per_dataset(self, db):
        # Same county name should map to the same ID regardless of context
        cache = {}
        id1 = get_or_create_county(db, "Nimba", cache)
        id2 = get_or_create_county(db, "Nimba", cache)
        assert id1 == id2

    def test_different_counties_get_different_ids(self, db):
        cache = {}
        id1 = get_or_create_county(db, "Bomi", cache)
        id2 = get_or_create_county(db, "Bong", cache)
        assert id1 != id2


# ===========================================================================
# load_dimensions
# ===========================================================================

class TestLoadDimensions:

    def test_all_unique_datasets_inserted(self, db, sample_df):
        d_cache, i_cache, c_cache = load_dimensions(db, sample_df)
        assert len(d_cache) == 2  # "Lisgis Census 2008" + "Employment Survey 2016"

    def test_all_unique_indicators_inserted(self, db, sample_df):
        d_cache, i_cache, c_cache = load_dimensions(db, sample_df)
        # 2 from Census (Total Population, Male Population) + 1 from Employment = 3
        assert len(i_cache) == 3

    def test_all_unique_counties_inserted(self, db, sample_df):
        d_cache, i_cache, c_cache = load_dimensions(db, sample_df)
        assert len(c_cache) == 2  # Montserrado, Nimba

    def test_indicator_key_is_name_plus_dataset_id(self, db, sample_df):
        d_cache, i_cache, c_cache = load_dimensions(db, sample_df)
        # All keys in indicator_cache must be (str, int) tuples
        for key in i_cache:
            assert isinstance(key, tuple)
            assert isinstance(key[0], str)
            assert isinstance(key[1], int)

    def test_dimensions_committed_to_db(self, db, sample_df):
        load_dimensions(db, sample_df)
        # After commit, a fresh query should find the rows
        assert db.query(Dataset).count() == 2
        assert db.query(County).count() == 2
        assert db.query(Indicator).count() == 3


# ===========================================================================
# load_observations
# ===========================================================================

class TestLoadObservations:

    def _setup_caches(self, db, df):
        return load_dimensions(db, df)

    def test_correct_number_inserted(self, db, sample_df):
        d_cache, i_cache, c_cache = self._setup_caches(db, sample_df)
        result = load_observations(db, sample_df, d_cache, i_cache, c_cache)
        assert result["inserted"] == 5
        assert result["skipped"]  == 0
        assert result["failed"]   == 0

    def test_duplicate_rows_are_skipped_not_failed(self, db, sample_df):
        d_cache, i_cache, c_cache = self._setup_caches(db, sample_df)
        # First load
        load_observations(db, sample_df, d_cache, i_cache, c_cache)
        # Second load — all rows are duplicates
        result = load_observations(db, sample_df, d_cache, i_cache, c_cache)
        assert result["inserted"] == 0
        assert result["skipped"]  == 5   # all 5 are duplicates
        assert result["failed"]   == 0

    def test_observation_values_stored_correctly(self, db, sample_df):
        d_cache, i_cache, c_cache = self._setup_caches(db, sample_df)
        load_observations(db, sample_df, d_cache, i_cache, c_cache)

        obs = db.query(Observation).join(Indicator).filter(
            Indicator.name == "Total Population"
        ).order_by(Observation.value.desc()).first()

        assert obs is not None
        assert obs.value == 1450000.0
        assert obs.year  == 2008

    def test_blank_value_stored_as_null(self, db):
        df = pd.DataFrame([{
            "dataset_name": "DS", "indicator_name": "Rate",
            "county": "Nimba", "year": "2022", "value": "",
        }])
        d_cache, i_cache, c_cache = load_dimensions(db, df)
        load_observations(db, df, d_cache, i_cache, c_cache)
        obs = db.query(Observation).first()
        assert obs is not None
        assert obs.value is None

    def test_rows_with_unknown_county_counted_as_failed(self, db, sample_df):
        d_cache, i_cache, c_cache = self._setup_caches(db, sample_df)
        # Inject a row with a county not in the cache
        bad_row = pd.DataFrame([{
            "dataset_name": "Lisgis Census 2008", "indicator_name": "Total Population",
            "county": "UNKNOWN_COUNTY_XYZ", "year": "2008", "value": "100",
        }])
        result = load_observations(db, bad_row, d_cache, i_cache, c_cache)
        assert result["failed"] == 1


# ===========================================================================
# run_db_load (integration)
# ===========================================================================

class TestRunDbLoad:

    def test_full_pipeline_inserts_all_rows(self, db, sample_df):
        summary = run_db_load(df=sample_df, db=db)
        assert summary["obs_inserted"] == 5
        assert summary["obs_failed"]   == 0

    def test_summary_contains_expected_keys(self, db, sample_df):
        summary = run_db_load(df=sample_df, db=db)
        expected = {
            "input_rows", "datasets_in_cache", "indicators_in_cache",
            "counties_in_cache", "obs_inserted", "obs_skipped", "obs_failed",
        }
        assert expected.issubset(set(summary.keys()))

    def test_empty_dataframe_returns_zero_counts(self, db):
        empty_df = pd.DataFrame(columns=[
            "dataset_name", "indicator_name", "county", "year", "value"
        ])
        summary = run_db_load(df=empty_df, db=db)
        assert summary["obs_inserted"] == 0

    def test_raises_on_missing_columns(self, db):
        bad_df = pd.DataFrame([{"county": "Nimba", "year": "2022"}])
        with pytest.raises(ValueError, match="missing required columns"):
            run_db_load(df=bad_df, db=db)

    def test_second_load_skips_duplicates(self, db, sample_df):
        run_db_load(df=sample_df, db=db)          # first load
        summary2 = run_db_load(df=sample_df, db=db)  # second load
        assert summary2["obs_inserted"] == 0
        assert summary2["obs_skipped"]  == 5

    def test_db_row_counts_match_summary(self, db, sample_df):
        summary = run_db_load(df=sample_df, db=db)
        assert db.query(Dataset).count()     == summary["datasets_in_cache"]
        assert db.query(County).count()      == summary["counties_in_cache"]
        assert db.query(Indicator).count()   == summary["indicators_in_cache"]
        assert db.query(Observation).count() == summary["obs_inserted"]
