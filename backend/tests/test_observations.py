"""
backend/tests/test_observations.py
=====================================
Tests for GET /api/v1/observations/ — the main data endpoint.

What is tested here:
  - The endpoint returns data in the correct shape
  - Each filter parameter (county, indicator, dataset, year) works correctly
  - Filters can be combined
  - Pagination (limit / offset) works correctly
  - Bad parameter values produce 422 Unprocessable Entity errors

How it works without a real database:
  We use an in-memory SQLite database (no PostgreSQL required).
  FastAPI's dependency injection lets us swap out `get_db` for our own
  function that returns the SQLite session.  All the SQLAlchemy query
  logic runs identically — only the underlying engine differs.

Run these tests:
    cd backend
    pytest tests/test_observations.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.session import Base, get_db
from app.models.models import Dataset, Indicator, County, Observation


# ============================================================
# Fixtures — database setup and TestClient wiring
# ============================================================

def _build_sqlite_session():
    """
    Create an in-memory SQLite database with all tables created.

    SQLite lives in RAM — no file, no cleanup, no external server.
    SQLAlchemy's ORM generates the same SQL structures regardless of
    the underlying database, so tests exercise the real query code.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        # Required: SQLite connections cannot be shared across threads
        # by default.  TestClient runs in the same thread, so this is safe.
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


def _seed_data(session):
    """
    Insert a small, predictable dataset for testing.

    Structure:
      2 datasets:   "Census 2008"  |  "Employment Survey"
      3 indicators: "Total Population", "Male Population", "Employment Rate"
      3 counties:   Nimba, Montserrado, Bong
      8 observations spanning 2008 and 2016
    """
    # ── Datasets ───────────────────────────────────────────────────────
    census     = Dataset(name="Census 2008",      description="LISGIS national census")
    employment = Dataset(name="Employment Survey", description="Annual employment data")
    session.add_all([census, employment])
    session.flush()     # populate .id without committing

    # ── Indicators ─────────────────────────────────────────────────────
    pop_total = Indicator(name="Total Population", dataset_id=census.id)
    pop_male  = Indicator(name="Male Population",  dataset_id=census.id)
    emp_rate  = Indicator(name="Employment Rate",  dataset_id=employment.id)
    session.add_all([pop_total, pop_male, emp_rate])
    session.flush()

    # ── Counties ───────────────────────────────────────────────────────
    nimba       = County(name="Nimba")
    montserrado = County(name="Montserrado")
    bong        = County(name="Bong")
    session.add_all([nimba, montserrado, bong])
    session.flush()

    # ── Observations ───────────────────────────────────────────────────
    # Census 2008 — Total Population (3 counties)
    # Census 2008 — Male Population  (2 counties, no Bong row)
    # Employment Survey 2016         (3 counties)
    session.add_all([
        Observation(dataset_id=census.id,     indicator_id=pop_total.id,
                    county_id=nimba.id,       year=2008, value=590_000.0),
        Observation(dataset_id=census.id,     indicator_id=pop_total.id,
                    county_id=montserrado.id, year=2008, value=1_450_000.0),
        Observation(dataset_id=census.id,     indicator_id=pop_total.id,
                    county_id=bong.id,        year=2008, value=350_000.0),
        Observation(dataset_id=census.id,     indicator_id=pop_male.id,
                    county_id=nimba.id,       year=2008, value=295_000.0),
        Observation(dataset_id=census.id,     indicator_id=pop_male.id,
                    county_id=montserrado.id, year=2008, value=720_000.0),
        Observation(dataset_id=employment.id, indicator_id=emp_rate.id,
                    county_id=nimba.id,       year=2016, value=49.1),
        Observation(dataset_id=employment.id, indicator_id=emp_rate.id,
                    county_id=montserrado.id, year=2016, value=58.3),
        Observation(dataset_id=employment.id, indicator_id=emp_rate.id,
                    county_id=bong.id,        year=2016, value=51.7),
    ])
    session.commit()


@pytest.fixture
def db_session():
    """
    Provide a clean, pre-seeded SQLite session for one test.

    Each test gets its own fresh database — tests cannot interfere
    with each other.
    """
    session = _build_sqlite_session()
    _seed_data(session)
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    """
    FastAPI TestClient with the real DB dependency replaced.

    How dependency overriding works:
      Normally FastAPI calls get_db() on each request to get a PostgreSQL
      session.  By setting app.dependency_overrides[get_db], we tell
      FastAPI to call our function instead — which yields the SQLite session.
      The route code never knows the difference.
    """
    def _use_test_db():
        yield db_session

    app.dependency_overrides[get_db] = _use_test_db

    with TestClient(app) as c:
        yield c

    # Clean up — always remove the override so other test modules are unaffected
    app.dependency_overrides.clear()


# ============================================================
# Tests: basic response shape
# ============================================================

class TestBasicResponse:
    """The endpoint must return 200 with a list of correctly shaped rows."""

    def test_returns_200(self, client):
        r = client.get("/api/v1/observations/")
        assert r.status_code == 200

    def test_returns_a_list(self, client):
        r = client.get("/api/v1/observations/")
        assert isinstance(r.json(), list)

    def test_unfiltered_returns_all_seeded_observations(self, client):
        # 8 observations seeded; default limit is 500 so all return
        r = client.get("/api/v1/observations/")
        assert len(r.json()) == 8

    def test_each_row_has_expected_fields(self, client):
        r    = client.get("/api/v1/observations/")
        row  = r.json()[0]
        required = {"id", "dataset_name", "indicator_name", "county", "year", "value"}
        assert required.issubset(row.keys())

    def test_names_not_raw_ids(self, client):
        """
        The response must use human-readable names, not database IDs.
        This is the ObservationExpanded shape — the join is doing its job.
        """
        r   = client.get("/api/v1/observations/")
        row = r.json()[0]
        assert isinstance(row["dataset_name"],   str)
        assert isinstance(row["indicator_name"], str)
        assert isinstance(row["county"],         str)

    def test_results_ordered_by_year_ascending(self, client):
        """API contract: results are always year asc, county asc."""
        r     = client.get("/api/v1/observations/")
        years = [row["year"] for row in r.json()]
        assert years == sorted(years)


# ============================================================
# Tests: filter by county
# ============================================================

class TestFilterByCounty:

    def test_only_matching_county_returned(self, client):
        r = client.get("/api/v1/observations/", params={"county": "Nimba"})
        assert r.status_code == 200
        for row in r.json():
            assert row["county"] == "Nimba"

    def test_correct_row_count_for_county(self, client):
        # Nimba has: Total Population + Male Population + Employment Rate = 3 rows
        r = client.get("/api/v1/observations/", params={"county": "Nimba"})
        assert len(r.json()) == 3

    def test_county_filter_is_case_insensitive(self, client):
        # "nimba" (lowercase) must still match "Nimba"
        r = client.get("/api/v1/observations/", params={"county": "nimba"})
        assert len(r.json()) == 3

    def test_county_partial_match(self, client):
        # "Mont" matches "Montserrado"
        r = client.get("/api/v1/observations/", params={"county": "Mont"})
        rows = r.json()
        assert len(rows) > 0
        for row in rows:
            assert row["county"] == "Montserrado"

    def test_nonexistent_county_returns_empty_list(self, client):
        r = client.get("/api/v1/observations/", params={"county": "Narnia"})
        assert r.status_code == 200
        assert r.json() == []


# ============================================================
# Tests: filter by indicator
# ============================================================

class TestFilterByIndicator:

    def test_exact_indicator_name(self, client):
        r = client.get("/api/v1/observations/",
                       params={"indicator_name": "Employment Rate"})
        rows = r.json()
        assert len(rows) == 3    # 3 counties for Employment Rate
        for row in rows:
            assert row["indicator_name"] == "Employment Rate"

    def test_partial_indicator_matches_multiple(self, client):
        # "population" matches both "Total Population" and "Male Population"
        r = client.get("/api/v1/observations/",
                       params={"indicator_name": "population"})
        names = {row["indicator_name"] for row in r.json()}
        assert "Total Population" in names
        assert "Male Population"  in names

    def test_indicator_filter_is_case_insensitive(self, client):
        r = client.get("/api/v1/observations/",
                       params={"indicator_name": "EMPLOYMENT RATE"})
        assert len(r.json()) == 3

    def test_unknown_indicator_returns_empty(self, client):
        r = client.get("/api/v1/observations/",
                       params={"indicator_name": "GDP Per Capita"})
        assert r.json() == []


# ============================================================
# Tests: filter by dataset
# ============================================================

class TestFilterByDataset:

    def test_dataset_filter_isolates_one_dataset(self, client):
        r = client.get("/api/v1/observations/",
                       params={"dataset_name": "Census 2008"})
        rows = r.json()
        # 3 Total Pop + 2 Male Pop = 5 observations in Census 2008
        assert len(rows) == 5
        for row in rows:
            assert row["dataset_name"] == "Census 2008"

    def test_dataset_partial_match(self, client):
        # "Employment" matches "Employment Survey"
        r = client.get("/api/v1/observations/",
                       params={"dataset_name": "Employment"})
        assert len(r.json()) == 3

    def test_unknown_dataset_returns_empty(self, client):
        r = client.get("/api/v1/observations/",
                       params={"dataset_name": "World Bank"})
        assert r.json() == []


# ============================================================
# Tests: filter by year
# ============================================================

class TestFilterByYear:

    def test_year_from_excludes_earlier_data(self, client):
        # year_from=2016 → only Employment Survey rows (2016) should appear
        r = client.get("/api/v1/observations/", params={"year_from": 2016})
        rows = r.json()
        assert len(rows) > 0
        for row in rows:
            assert row["year"] >= 2016

    def test_year_to_excludes_later_data(self, client):
        # year_to=2008 → only Census rows (2008) should appear
        r = client.get("/api/v1/observations/", params={"year_to": 2008})
        rows = r.json()
        assert len(rows) > 0
        for row in rows:
            assert row["year"] <= 2008

    def test_year_range_narrows_to_one_year(self, client):
        r = client.get("/api/v1/observations/",
                       params={"year_from": 2016, "year_to": 2016})
        rows = r.json()
        assert len(rows) == 3    # Employment Rate, 3 counties
        for row in rows:
            assert row["year"] == 2016

    def test_year_range_with_no_data_returns_empty(self, client):
        r = client.get("/api/v1/observations/",
                       params={"year_from": 1990, "year_to": 2000})
        assert r.json() == []


# ============================================================
# Tests: combined filters
# ============================================================

class TestCombinedFilters:
    """Multiple filters applied together narrow results further."""

    def test_county_and_indicator(self, client):
        r = client.get("/api/v1/observations/", params={
            "county":         "Nimba",
            "indicator_name": "Employment Rate",
        })
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["county"]         == "Nimba"
        assert rows[0]["indicator_name"] == "Employment Rate"
        assert rows[0]["value"]          == pytest.approx(49.1)

    def test_dataset_and_county(self, client):
        # Only Total Population has a Bong row in Census 2008
        # (Male Population has no Bong observation in our seed data)
        r = client.get("/api/v1/observations/", params={
            "dataset_name": "Census 2008",
            "county":       "Bong",
        })
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["county"]       == "Bong"
        assert rows[0]["dataset_name"] == "Census 2008"

    def test_three_filters_pin_to_one_row(self, client):
        r = client.get("/api/v1/observations/", params={
            "indicator_name": "Total Population",
            "county":         "Montserrado",
            "year_from":      2008,
            "year_to":        2008,
        })
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["value"] == pytest.approx(1_450_000.0)

    def test_contradictory_filters_return_empty(self, client):
        # Employment Rate only exists in 2016; year_to=2010 excludes it
        r = client.get("/api/v1/observations/", params={
            "indicator_name": "Employment Rate",
            "year_to":        2010,
        })
        assert r.json() == []


# ============================================================
# Tests: pagination
# ============================================================

class TestPagination:

    def test_limit_restricts_number_of_rows(self, client):
        r = client.get("/api/v1/observations/", params={"limit": 3})
        assert len(r.json()) == 3

    def test_offset_skips_rows(self, client):
        all_rows    = client.get("/api/v1/observations/").json()
        offset_rows = client.get("/api/v1/observations/",
                                 params={"offset": 2}).json()
        # Rows with offset=2 must start at what was index 2 in the full list
        assert len(offset_rows) == len(all_rows) - 2
        assert offset_rows[0]   == all_rows[2]

    def test_limit_and_offset_together(self, client):
        r = client.get("/api/v1/observations/",
                       params={"limit": 2, "offset": 3})
        assert len(r.json()) == 2

    def test_offset_beyond_data_returns_empty(self, client):
        r = client.get("/api/v1/observations/", params={"offset": 9999})
        assert r.json() == []


# ============================================================
# Tests: input validation (Pydantic constraints)
# ============================================================

class TestInputValidation:
    """
    FastAPI / Pydantic rejects bad parameter values before the query runs.
    These tests confirm the validation is wired correctly.
    """

    def test_limit_zero_is_rejected(self, client):
        # limit has ge=1 — zero is not allowed
        r = client.get("/api/v1/observations/", params={"limit": 0})
        assert r.status_code == 422

    def test_limit_above_max_is_rejected(self, client):
        # limit has le=5000
        r = client.get("/api/v1/observations/", params={"limit": 9999})
        assert r.status_code == 422

    def test_year_from_before_minimum_is_rejected(self, client):
        # year_from has ge=1970
        r = client.get("/api/v1/observations/", params={"year_from": 1800})
        assert r.status_code == 422

    def test_year_to_after_maximum_is_rejected(self, client):
        # year_to has le=2035
        r = client.get("/api/v1/observations/", params={"year_to": 2100})
        assert r.status_code == 422

    def test_negative_offset_is_rejected(self, client):
        # offset has ge=0
        r = client.get("/api/v1/observations/", params={"offset": -1})
        assert r.status_code == 422
