"""
backend/app/api/router.py
==========================
Central API router — the single place that registers all route modules.

All routes are mounted under /api/v1 (set in main.py).

Full endpoint map:
  GET  /health/                 — liveness check
  GET  /health/db               — database connectivity check
  GET  /datasets/               — list all datasets
  GET  /datasets/{id}           — single dataset
  GET  /indicators/             — list all indicators (with search + dataset filter)
  GET  /indicators/{id}         — single indicator
  GET  /counties/               — list all counties
  GET  /observations/           — filtered observations (main data endpoint)
  GET  /summary/                — system-wide statistics
  GET  /summary/trend           — time-series for one indicator + county
  GET  /summary/compare         — cross-county comparison for one indicator + year
  POST /ai/query                — natural language query (requires ANTHROPIC_API_KEY)
  GET  /download/cleaned        — export filtered observations as CSV
"""

from fastapi import APIRouter

from app.api.routes import (
    health,
    datasets,
    indicators,
    counties,
    observations,
    summary,
    ai_query,
    download,
)

api_router = APIRouter()

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
api_router.include_router(health.router,       prefix="/health",       tags=["health"])

# ---------------------------------------------------------------------------
# Dimension resources
# ---------------------------------------------------------------------------
api_router.include_router(datasets.router,     prefix="/datasets",     tags=["datasets"])
api_router.include_router(indicators.router,   prefix="/indicators",   tags=["indicators"])
api_router.include_router(counties.router,     prefix="/counties",     tags=["counties"])

# ---------------------------------------------------------------------------
# Core data
# ---------------------------------------------------------------------------
api_router.include_router(observations.router, prefix="/observations", tags=["observations"])

# ---------------------------------------------------------------------------
# Aggregates and summaries
# ---------------------------------------------------------------------------
api_router.include_router(summary.router,      prefix="/summary",      tags=["summary"])

# ---------------------------------------------------------------------------
# AI layer
# ---------------------------------------------------------------------------
api_router.include_router(ai_query.router,     prefix="/ai",           tags=["ai-query"])

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
api_router.include_router(download.router,     prefix="/download",     tags=["download"])
