"""
backend/app/main.py
====================
FastAPI application entry point.

This file:
  1. Creates the FastAPI app instance.
  2. Configures logging.
  3. Adds middleware (CORS).
  4. Registers all API routes.
  5. Defines startup/shutdown lifecycle events.

Run locally:
    uvicorn app.main:app --reload --port 8000

Then visit:
    http://localhost:8000/docs      (interactive Swagger UI)
    http://localhost:8000/health    (liveness check)
    http://localhost:8000/health/db (database check)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.api.router import api_router
from app.db.session import engine, Base, SessionLocal
import app.models.models  # noqa: F401 — registers models with Base
from app.models.models import Dataset

# ---------------------------------------------------------------------------
# Configure logging FIRST — before anything else logs
# ---------------------------------------------------------------------------
configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifecycle (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code inside the `yield` runs on startup.
    Code after the `yield` runs on shutdown.

    This is the modern FastAPI replacement for @app.on_event("startup").
    """
    # --- Startup ---
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")

    # ONE-TIME CLEANUP: remove datasets whose names end with "Liberia"
    db = SessionLocal()
    try:
        liberia_datasets = db.query(Dataset).filter(Dataset.name.ilike("%Liberia")).all()
        for ds in liberia_datasets:
            logger.info("Removing duplicate dataset: %r (id=%s)", ds.name, ds.id)
            db.delete(ds)
        db.commit()
        if liberia_datasets:
            logger.info("Cleanup complete: %d dataset(s) removed.", len(liberia_datasets))
    finally:
        db.close()

    logger.info("=== %s v%s starting ===", settings.app_name, settings.app_version)
    logger.info("Environment : %s", settings.app_env)
    logger.info("API docs    : http://%s:%s/docs", settings.api_host, settings.api_port)

    yield  # Application runs here

    # --- Shutdown ---
    logger.info("=== %s shutting down ===", settings.app_name)


# ---------------------------------------------------------------------------
# Create the FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title       = settings.app_name,
    version     = settings.app_version,
    description = (
        "Unified access layer for Liberia public statistics. "
        "Transforms raw datasets from LISGIS and partner agencies into "
        "a standardised, queryable intelligence layer. "
        "Indicator-based — not county-based."
    ),
    # Interactive docs are available in all environments for now.
    # In production you may want to set docs_url=None to disable them.
    docs_url  = "/docs",
    redoc_url = "/redoc",
    lifespan  = lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
# CORS: Cross-Origin Resource Sharing.
# This controls which domains are allowed to call the API from a browser.
# In development we allow all origins. Restrict this in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"] if settings.app_env == "development" else [],
    allow_methods  = ["GET", "POST", "OPTIONS"],
    allow_headers  = ["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
# Mount all routes under /api/v1 — this makes versioning easy later.
app.include_router(api_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Root endpoint (outside /api/v1 for convenience)
# ---------------------------------------------------------------------------
@app.get("/", tags=["root"], include_in_schema=False)
def root():
    """
    Root endpoint — useful for a quick browser check.
    Not part of the official API surface.
    """
    return {
        "project": settings.app_name,
        "version": settings.app_version,
        "status":  "running",
        "docs":    "/docs",
        "health":  "/api/v1/health",
    }
