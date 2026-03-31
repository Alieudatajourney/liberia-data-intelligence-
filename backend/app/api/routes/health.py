"""
backend/app/api/routes/health.py
==================================
Health check endpoints.

Purpose:
  - Let monitoring tools (Docker, Kubernetes, uptime checkers) verify
    that the API is alive.
  - Provide a deeper check that also tests the database connection.

Endpoints:
  GET /health        — basic liveness check (is the process running?)
  GET /health/db     — readiness check (can we reach the database?)
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)

# All routes in this file will be prefixed with /health
# (The prefix is set in router.py)
router = APIRouter()


@router.get(
    "/",
    summary="Liveness check",
    description="Returns 200 OK if the API process is running.",
)
def health_check():
    """
    Basic liveness check.

    If this returns 200, the API server is running.
    It does NOT check the database or any other dependency.
    """
    return {
        "status": "ok",
        "app":    settings.app_name,
        "version": settings.app_version,
        "env":    settings.app_env,
    }


@router.get(
    "/db",
    summary="Database readiness check",
    description="Returns 200 OK if the API can connect to the database.",
)
def health_check_db(db: Session = Depends(get_db)):
    """
    Database readiness check.

    Runs a trivial query (SELECT 1) to confirm the DB connection is alive.
    Returns 503 if the database is unreachable.
    """
    try:
        db.execute(text("SELECT 1"))
        logger.info("Database health check passed.")
        return {
            "status":   "ok",
            "database": "connected",
        }
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Database connection failed: {exc}",
        )
