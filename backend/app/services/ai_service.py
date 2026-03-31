"""
backend/app/services/ai_service.py
=====================================
AI-assisted natural language query service.

How it works:
  1. Receives a plain English question from the user.
  2. Sends the question to Claude with a structured system prompt that
     describes the data schema and available counties/indicators.
  3. Claude returns a JSON object with extracted filters and explanation.
  4. The service runs a standard observation query using those filters.
  5. Returns a fully populated AIQueryResponse.

Security design:
  Claude NEVER generates SQL.  It only produces a filter dict that is
  applied to the database using the same SQLAlchemy code as the regular
  /observations endpoint.  This completely prevents prompt injection
  from producing arbitrary database access.

Graceful degradation:
  If ANTHROPIC_API_KEY is not set, the endpoint returns a well-formed
  response with ai_available=False.  No exception is raised — the
  dashboard can display a helpful "AI disabled" message.
"""

import json
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.ai_query import AIQueryRequest, AIQueryResponse, ExtractedFilters
from app.services.query_service import query_observations

logger = logging.getLogger(__name__)

# Maximum observations returned in the result preview (not the full query)
PREVIEW_LIMIT = 10

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
# Describes the data schema to Claude.  Keep it concise — token costs money.

_SYSTEM_PROMPT = """
You are a data assistant for the Liberia Public Data Intelligence system.

The database holds public statistics for Liberia. Each data point has:
  - dataset_name   : source dataset, e.g. "Lisgis Census 2008"
  - indicator_name : what is measured, e.g. "Total Population", "Employment Rate"
  - county         : one of Liberia's 15 counties, or "National"
  - year           : 4-digit integer
  - value          : numeric value

Liberia's 15 counties:
  Bomi, Bong, Gbarpolu, Grand Bassa, Grand Cape Mount, Grand Gedeh,
  Grand Kru, Lofa, Margibi, Maryland, Montserrado, Nimba,
  Rivercess, River Gee, Sinoe.

Given a natural language question, respond ONLY with valid JSON:
{
  "detected_intent": "One sentence describing what the user is asking for.",
  "filters": {
    "dataset_name":   "partial dataset name or null",
    "indicator_name": "partial indicator name or null",
    "county":         "county name or null",
    "year_from":      2000,
    "year_to":        2022
  },
  "explanation": "One or two sentences explaining what this data shows."
}

Rules:
  - Only include filter keys that are relevant to the question.
  - Use partial/substring values for indicator_name — do not invent exact names.
  - If the question has no data relevance, return empty filters and explain why.
  - Never include SQL.
  - Never include text outside the JSON object.
""".strip()


# ---------------------------------------------------------------------------
# AI filter extraction
# ---------------------------------------------------------------------------

def _extract_filters_from_question(question: str) -> tuple[ExtractedFilters, str, str]:
    """
    Call Claude to parse a natural language question into structured filters.

    Args:
        question : The user's plain English question.

    Returns:
        (filters, detected_intent, explanation)

    Raises:
        RuntimeError : If the Anthropic API call fails or returns invalid JSON.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model      = "claude-opus-4-6",
        max_tokens = 512,
        system     = _SYSTEM_PROMPT,
        messages   = [{"role": "user", "content": question}],
    )

    raw = response.content[0].text.strip()
    logger.debug("AI raw response: %s", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"AI returned non-JSON response: {raw[:200]}"
        ) from exc

    raw_filters  = parsed.get("filters", {})
    detected     = parsed.get("detected_intent", "")
    explanation  = parsed.get("explanation", "")

    # Build a validated ExtractedFilters from whatever the AI returned
    filters = ExtractedFilters(
        dataset_name   = raw_filters.get("dataset_name"),
        indicator_name = raw_filters.get("indicator_name"),
        county         = raw_filters.get("county"),
        year_from      = raw_filters.get("year_from"),
        year_to        = raw_filters.get("year_to"),
    )

    return filters, detected, explanation


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ai_query(request: AIQueryRequest, db: Session) -> AIQueryResponse:
    """
    Handle a natural language query end-to-end.

    Args:
        request : AIQueryRequest containing the user's question.
        db      : Active SQLAlchemy session.

    Returns:
        AIQueryResponse — always returns a valid object, never raises.
        If the AI is disabled or fails, ai_available=False and
        explanation contains the reason.
    """
    # --- Check if AI is available ---
    if not settings.anthropic_api_key:
        logger.warning("AI query attempted but ANTHROPIC_API_KEY is not set.")
        return AIQueryResponse(
            question        = request.question,
            detected_intent = "",
            filters_applied = ExtractedFilters(),
            result_count    = 0,
            result_preview  = [],
            explanation     = (
                "The AI query layer is currently disabled. "
                "Set ANTHROPIC_API_KEY in your .env file to enable it. "
                "You can still use GET /api/v1/observations to filter data directly."
            ),
            ai_available    = False,
        )

    # --- Extract filters ---
    try:
        filters, detected_intent, ai_explanation = _extract_filters_from_question(
            request.question
        )
    except Exception as exc:
        logger.error("AI filter extraction failed: %s", exc)
        return AIQueryResponse(
            question        = request.question,
            detected_intent = "",
            filters_applied = ExtractedFilters(),
            result_count    = 0,
            result_preview  = [],
            explanation     = f"The AI could not process this question: {exc}",
            ai_available    = True,
        )

    logger.info(
        "AI extracted filters: %s | intent: %s",
        filters.model_dump(exclude_none=True),
        detected_intent,
    )

    # --- Run the database query using AI-extracted filters ---
    # Full count first (no limit), then preview (limited)
    all_results = query_observations(
        db             = db,
        dataset_name   = filters.dataset_name,
        indicator_name = filters.indicator_name,
        county         = filters.county,
        year_from      = filters.year_from,
        year_to        = filters.year_to,
        limit          = 5000,   # generous limit for count
        offset         = 0,
    )

    preview = all_results[:PREVIEW_LIMIT]

    return AIQueryResponse(
        question        = request.question,
        detected_intent = detected_intent,
        filters_applied = filters,
        result_count    = len(all_results),
        result_preview  = preview,
        explanation     = ai_explanation,
        ai_available    = True,
    )
