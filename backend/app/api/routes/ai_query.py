"""
backend/app/api/routes/ai_query.py
=====================================
Route for the AI-assisted natural language query endpoint.

Endpoint:
  POST /ai/query   — submit a plain English question, get data + explanation

Response fields:
  intent_type      : classified intent (trend | comparison | summary | rejected | "")
  detected_intent  : one sentence describing what the AI understood
  rejection_reason : why the query was rejected (null if not rejected)
  filters_applied  : the structured query parameters derived from the question
  query_executed   : True if a database query actually ran
  result_count     : total matching observations (0 if query_executed=False)
  result_preview   : first 10 real observations (never fabricated)
  explanation      : plain-English summary generated from actual results
  ai_available     : False when ANTHROPIC_API_KEY is not configured

Why always HTTP 200?
  The endpoint never returns 4xx/5xx for AI-layer failures.  Rejection and
  degradation are communicated through response body fields (intent_type,
  ai_available, rejection_reason) so the dashboard can render useful
  messages without handling HTTP error codes.

  Infrastructure failures (DB down, etc.) may still produce 500s —
  those come from FastAPI's exception handlers, not this route.
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.ai_query import AIQueryRequest, AIQueryResponse
from app.services.ai_query_service import run_ai_query

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/query",
    response_model = AIQueryResponse,
    summary        = "Natural language query",
    description    = (
        "Submit a plain English question about Liberia public data. "
        "The AI classifies the intent, extracts structured filters, "
        "runs a safe database query, and returns an explanation based on "
        "the actual results.\n\n"

        "**Supported intent types:**\n"
        "- **trend** — how one indicator changes over time in one county\n"
        "- **comparison** — one indicator across all counties in one year\n"
        "- **summary** — general lookup for an indicator or dataset\n\n"

        "**Rejected questions:**\n"
        "- Vague or off-topic questions\n"
        "- Questions missing required parameters\n"
        "- Multi-indicator or multi-county requests (v1 limitation)\n\n"

        "**Example questions:**\n"
        "- `'How has Total Population changed in Nimba county?'`\n"
        "- `'Compare employment rates across all counties in 2016'`\n"
        "- `'Show malaria data for Montserrado'`\n\n"

        "If `ai_available` is `false`, set `ANTHROPIC_API_KEY` in your "
        "`.env` file to enable this feature. "
        "If `intent_type` is `'rejected'`, see `rejection_reason` for guidance."
    ),
)
def ai_query(
    request: AIQueryRequest,
    db:      Session = Depends(get_db),
) -> AIQueryResponse:
    """
    Process a natural language question against the Liberia database.

    Safety guarantees:
      - The AI never generates SQL.
      - The AI never sees the database directly.
      - Results are always real data from the database.
      - Explanations are generated from actual results, not invented.
      - Invalid/vague questions are rejected before any query runs.

    Always returns HTTP 200.  Check response fields to determine outcome.
    """
    logger.info("AI query received: %r", request.question)

    response = run_ai_query(request=request, db=db)

    logger.info(
        "AI query complete: intent=%r executed=%s count=%d available=%s",
        response.intent_type,
        response.query_executed,
        response.result_count,
        response.ai_available,
    )

    return response
