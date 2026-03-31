"""
backend/tests/test_health.py
==============================
Tests for the /health endpoints.

These are the first tests in the project — they verify the skeleton is
wired correctly before any business logic is added.

Run tests:
    cd backend
    pytest tests/ -v
"""

from fastapi.testclient import TestClient
from app.main import app

# TestClient wraps the FastAPI app and lets you make requests
# without running a real server.  Useful for unit tests.
client = TestClient(app)


def test_root_returns_200():
    """The root endpoint should be reachable."""
    response = client.get("/")
    assert response.status_code == 200


def test_root_returns_project_name():
    """Root response should include the project name."""
    response = client.get("/")
    data = response.json()
    assert "project" in data
    assert "Liberia" in data["project"]


def test_health_liveness():
    """GET /api/v1/health should return status: ok."""
    response = client.get("/api/v1/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_health_includes_version():
    """Health response should include app version."""
    response = client.get("/api/v1/health/")
    data = response.json()
    assert "version" in data


# Note: test_health_db is intentionally omitted here because it requires
# a real database connection.  Add it to an integration test suite later.
