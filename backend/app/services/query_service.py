"""
backend/app/services/query_service.py
========================================
Backward-compatibility re-export facade.

The real logic now lives in:
  - observation_service.py  →  filter_observations, count_observations
  - summary_service.py      →  get_system_summary, get_trend, get_comparison

This module re-exports the original public names so that any existing
callers (ai_service.py, tests, etc.) continue to work unchanged.

Do NOT add new logic here.  Add it to the appropriate service module instead.
"""

from app.services.observation_service import (   # noqa: F401
    filter_observations as query_observations,
    count_observations,
)

from app.services.summary_service import (       # noqa: F401
    get_system_summary,
    get_trend,
    get_comparison,
)
