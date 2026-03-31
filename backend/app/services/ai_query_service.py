"""
backend/app/services/ai_query_service.py
==========================================
Safe AI-assisted natural language query service.

WHY THIS APPROACH IS SAFER THAN LETTING AI WRITE SQL
------------------------------------------------------
Allowing an LLM to generate raw SQL creates several attack surfaces:

  1. Prompt injection — a crafted question like:
       "Show population; DROP TABLE observations; --"
     could be converted to destructive SQL.

  2. Data exfiltration — the AI could generate queries that return
     data outside the intended scope (other tables, all rows, etc.).

  3. Hallucination of results — if the AI is asked to explain data
     it has not seen, it may invent plausible-sounding but wrong numbers.

  4. Schema leakage — SQL generation requires the AI to know your exact
     table/column names, which increases the blast radius of a model
     compromise.

This service avoids all of these by design:

  - The AI ONLY produces a JSON filter object with known keys.
  - The database query is always run by the same SQLAlchemy code that
    powers GET /observations — no custom SQL, no dynamic table names.
  - The explanation is generated AFTER the real results arrive,
    so it describes actual data rather than hallucinated data.
  - County names are validated against a hardcoded canonical list
    before the query runs.
  - Year ranges are sanity-checked before the query runs.
  - Intent classification gates which filters are required — a trend
    query without a county is rejected before touching the database.

V1 LIMITATIONS
--------------
  1. Intent classification uses a single LLM call and is not perfect.
     Ambiguous questions may be misclassified.

  2. Indicator matching is substring-based (ILIKE).  If the user asks
     about "school enrollment" but the indicator is stored as "Net
     Enrolment Rate", the query may return zero results.  A future
     version could add embedding-based semantic search.

  3. Multi-indicator and multi-county questions are not supported.
     "Compare population AND literacy in Nimba AND Bong" will be
     partially parsed or rejected.

  4. The explanation call adds latency (~1s).  A future version could
     stream the explanation after the data rows are sent.

  5. There is no caching.  Identical questions hit the LLM every time.

PUBLIC API
----------
  run_ai_query(request, db) → AIQueryResponse
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.ai_query import (
    AIQueryRequest,
    AIQueryResponse,
    ExtractedFilters,
)
from app.schemas.observation import ObservationExpanded
from app.services.observation_service import filter_observations, count_observations

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PREVIEW_LIMIT = 10      # rows included in result_preview
YEAR_MIN      = 1970
YEAR_MAX      = 2035

# Canonical county names (lowercase for comparison).
# "national" is valid for aggregate/national-level rows.
LIBERIA_COUNTIES: frozenset[str] = frozenset({
    "bomi", "bong", "gbarpolu", "grand bassa", "grand cape mount",
    "grand gedeh", "grand kru", "lofa", "margibi", "maryland",
    "montserrado", "nimba", "rivercess", "river gee", "sinoe",
    "national",
})


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """
You are a query extraction assistant for the Liberia Public Data Intelligence system.

DATABASE SCHEMA
Each observation has five fields:
  dataset_name   — source dataset, e.g. "Lisgis Census 2008"
  indicator_name — what is measured, e.g. "Total Population", "Employment Rate"
  county         — Liberia county or "National" for aggregates
  year           — 4-digit integer (1970–2035)
  value          — numeric measurement

LIBERIA'S 15 COUNTIES (only these are valid):
  Bomi, Bong, Gbarpolu, Grand Bassa, Grand Cape Mount, Grand Gedeh,
  Grand Kru, Lofa, Margibi, Maryland, Montserrado, Nimba,
  Rivercess, River Gee, Sinoe.
  "National" is also valid for aggregate/country-level data.

INTENT TYPES
  trend      — user asks how one indicator changes over TIME in ONE county
  comparison — user asks how ONE indicator compares ACROSS counties in ONE year
  summary    — user asks for a general lookup, a single value, or a broad summary
  rejected   — question is vague, off-topic, a greeting, requests non-Liberia data,
               lacks the minimum information needed, or is not a data question

MINIMUM REQUIRED FILTERS PER INTENT
  trend:      indicator_name (required) + county (required)
  comparison: indicator_name (required) + year_from set to the specific year (required)
  summary:    at least indicator_name OR dataset_name must be present
  rejected:   no requirements — use this when you cannot extract a valid query

RESPONSE FORMAT
Return ONLY this JSON object. No text before or after it.

{
  "intent_type": "trend" | "comparison" | "summary" | "rejected",
  "detected_intent": "One sentence describing what the user is asking for.",
  "rejection_reason": "Brief reason for rejection, or null if not rejected.",
  "filters": {
    "dataset_name":   "partial dataset name, or null",
    "indicator_name": "short partial indicator substring, or null",
    "county":         "exact canonical county name from the list above, or null",
    "year_from":      integer or null,
    "year_to":        integer or null
  }
}

RULES
  1. Never generate SQL. Never include SQL in any field.
  2. For indicator_name use SHORT substrings that will match via ILIKE:
       "population" not "Total Population of Liberia By County"
       "employment" not "Employment Rate Among Working Age Adults"
  3. If a county is mentioned, use its exact canonical name from the list above.
  4. For comparison queries, set year_from = year_to = the specific year mentioned.
  5. Set fields to null rather than guessing — do not invent information.
  6. If the question asks about multiple indicators or multiple counties
     simultaneously, set intent_type to "rejected" with a clear reason.
  7. If the question is a greeting, test, or has no data relevance, reject it.
  8. If you are not confident about a filter value, set it to null.
""".strip()


_EXPLANATION_SYSTEM_PROMPT = """
You are a data analyst presenting findings from the Liberia Public Data Intelligence system.

You will receive:
  - The user's original question
  - The classified intent type
  - The filters that were used
  - The actual data results (up to 10 rows)
  - The total number of matching rows

Write a clear, factual explanation of 2–4 sentences.

RULES
  1. Only describe what the actual data shows — never invent numbers.
  2. If no results were found, say so clearly and suggest the user broaden their filters.
  3. Include specific values, county names, and years from the actual data.
  4. Do not mention SQL, APIs, databases, filters, or technical terms.
  5. Write in plain English for a non-technical reader.
  6. Do not start with "The data shows" every time — vary your opening.
  7. If there are many results, summarize the key pattern rather than listing every row.
""".strip()


# ---------------------------------------------------------------------------
# Claude API wrapper
# ---------------------------------------------------------------------------

def _call_claude(
    system_prompt: str,
    user_message:  str,
    max_tokens:    int = 512,
) -> str:
    """
    Call the Claude API and return the raw text response.

    Args:
        system_prompt : The system instructions for Claude.
        user_message  : The user-facing message content.
        max_tokens    : Maximum response length in tokens.

    Returns:
        Raw text from the first content block.

    Raises:
        RuntimeError : On API failure or empty response.
    """
    import anthropic  # imported here so startup doesn't fail if not installed

    client   = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model    = "claude-opus-4-6",
        max_tokens = max_tokens,
        system   = system_prompt,
        messages = [{"role": "user", "content": user_message}],
    )

    if not response.content:
        raise RuntimeError("Claude returned an empty response.")

    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Step 1: Intent classification + filter extraction
# ---------------------------------------------------------------------------

def _classify_and_extract(
    question: str,
) -> tuple[str, str, str | None, ExtractedFilters]:
    """
    Call Claude to classify the question and extract structured filters.

    Args:
        question: The user's plain English question.

    Returns:
        (intent_type, detected_intent, rejection_reason, filters)

    Raises:
        RuntimeError: If the API call fails or the response is not valid JSON.
    """
    raw = _call_claude(
        system_prompt = _EXTRACTION_SYSTEM_PROMPT,
        user_message  = question,
        max_tokens    = 512,
    )
    logger.debug("AI extraction raw response: %s", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"AI returned non-JSON during extraction: {raw[:300]}"
        ) from exc

    intent_type      = str(parsed.get("intent_type", "rejected")).lower()
    detected_intent  = str(parsed.get("detected_intent", "")).strip()
    rejection_reason = parsed.get("rejection_reason")  # str or None

    raw_filters = parsed.get("filters") or {}

    # Coerce year values to int (AI may return them as strings)
    def _to_int(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    filters = ExtractedFilters(
        dataset_name   = raw_filters.get("dataset_name") or None,
        indicator_name = raw_filters.get("indicator_name") or None,
        county         = raw_filters.get("county") or None,
        year_from      = _to_int(raw_filters.get("year_from")),
        year_to        = _to_int(raw_filters.get("year_to")),
    )

    return intent_type, detected_intent, rejection_reason, filters


# ---------------------------------------------------------------------------
# Step 2: Safety validation
# ---------------------------------------------------------------------------

def _validate_intent_and_filters(
    intent_type: str,
    filters:     ExtractedFilters,
) -> tuple[bool, str | None]:
    """
    Check that the extracted filters are sufficient for the declared intent.

    This is the safety gate that prevents under-specified queries from
    reaching the database.  Returns (is_valid, rejection_reason).

    Args:
        intent_type : The AI-classified intent.
        filters     : The extracted filter object.

    Returns:
        (True, None)         if the query is valid.
        (False, "reason")    if the query should be rejected.
    """
    if intent_type == "rejected":
        return False, None  # already rejected by the AI; reason is in rejection_reason

    if intent_type not in {"trend", "comparison", "summary"}:
        return False, f"Unrecognised intent type: '{intent_type}'."

    # --- Intent-specific required fields ---
    if intent_type == "trend":
        if not filters.indicator_name:
            return False, (
                "Trend queries require an indicator name. "
                "Try: 'How has population changed in Nimba?'"
            )
        if not filters.county:
            return False, (
                "Trend queries require a county name. "
                "Try: 'How has employment changed in Montserrado over time?'"
            )

    elif intent_type == "comparison":
        if not filters.indicator_name:
            return False, (
                "Comparison queries require an indicator name. "
                "Try: 'Compare employment rates across counties in 2016.'"
            )
        if filters.year_from is None:
            return False, (
                "Comparison queries require a specific year. "
                "Try: 'Compare literacy rates across counties in 2008.'"
            )

    elif intent_type == "summary":
        if not filters.indicator_name and not filters.dataset_name:
            return False, (
                "Summary queries need at least an indicator or dataset name. "
                "Try: 'Show population data' or 'What health indicators are available?'"
            )

    # --- County name validation ---
    if filters.county:
        county_lower = filters.county.lower()
        # Allow partial matches against the canonical list
        if not any(
            county_lower in canonical or canonical in county_lower
            for canonical in LIBERIA_COUNTIES
        ):
            return False, (
                f"'{filters.county}' is not a recognised Liberia county. "
                f"Valid counties: Bomi, Bong, Gbarpolu, Grand Bassa, Grand Cape Mount, "
                f"Grand Gedeh, Grand Kru, Lofa, Margibi, Maryland, Montserrado, Nimba, "
                f"Rivercess, River Gee, Sinoe."
            )

    # --- Year range sanity ---
    if filters.year_from is not None:
        if not (YEAR_MIN <= filters.year_from <= YEAR_MAX):
            return False, (
                f"year_from {filters.year_from} is out of the supported range "
                f"({YEAR_MIN}–{YEAR_MAX})."
            )
    if filters.year_to is not None:
        if not (YEAR_MIN <= filters.year_to <= YEAR_MAX):
            return False, (
                f"year_to {filters.year_to} is out of the supported range "
                f"({YEAR_MIN}–{YEAR_MAX})."
            )
    if filters.year_from is not None and filters.year_to is not None:
        if filters.year_from > filters.year_to:
            return False, (
                f"year_from ({filters.year_from}) must not be greater than "
                f"year_to ({filters.year_to})."
            )

    return True, None


# ---------------------------------------------------------------------------
# Step 3: Explanation generation
# ---------------------------------------------------------------------------

def _format_results_for_explanation(
    results:     list[ObservationExpanded],
    total_count: int,
    intent_type: str,
) -> str:
    """
    Format result rows as plain text for the explanation prompt.

    We limit to PREVIEW_LIMIT rows and label each one.  This keeps the
    prompt token-efficient while giving Claude enough signal to write
    an accurate explanation.
    """
    if not results:
        return "No results found."

    lines = [f"Total matching rows: {total_count}"]
    if total_count > len(results):
        lines.append(f"(Showing first {len(results)} of {total_count})")
    lines.append("")

    for obs in results:
        value_str = str(obs.value) if obs.value is not None else "N/A"
        lines.append(
            f"  [{obs.dataset_name}] {obs.indicator_name} | "
            f"{obs.county} | {obs.year} | {value_str}"
        )

    return "\n".join(lines)


def _generate_explanation(
    question:       str,
    intent_type:    str,
    detected_intent: str,
    filters:        ExtractedFilters,
    results:        list[ObservationExpanded],
    total_count:    int,
) -> str:
    """
    Generate a plain-English explanation from actual result data.

    This is the second AI call — it runs AFTER the database query so the
    explanation is grounded in real numbers, not invented ones.

    Args:
        question:        The original user question.
        intent_type:     The classified intent.
        detected_intent: One-line summary of what was understood.
        filters:         The filters that were applied.
        results:         The actual result rows (may be empty).
        total_count:     Total matching rows (without limit).

    Returns:
        Plain-English explanation string.
    """
    active_filters = {
        k: v for k, v in filters.model_dump().items() if v is not None
    }

    user_message = (
        f"User question: {question}\n"
        f"Intent: {intent_type} — {detected_intent}\n"
        f"Filters applied: {json.dumps(active_filters, indent=2)}\n\n"
        f"Data results:\n"
        f"{_format_results_for_explanation(results, total_count, intent_type)}"
    )

    try:
        return _call_claude(
            system_prompt = _EXPLANATION_SYSTEM_PROMPT,
            user_message  = user_message,
            max_tokens    = 256,
        )
    except Exception as exc:
        logger.warning("Explanation generation failed: %s", exc)
        if not results:
            return (
                "No data was found matching your query. "
                "Try broadening your filters or use GET /indicators to find exact indicator names."
            )
        return (
            f"Found {total_count} matching observation(s). "
            "Use the result_preview to explore the data."
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ai_query(request: AIQueryRequest, db: Session) -> AIQueryResponse:
    """
    Handle a natural language query end-to-end, safely.

    Flow:
      1. Check AI is available (API key present).
      2. Call Claude to classify intent and extract filters (Step 1).
      3. Validate filters against intent requirements (Step 2).
      4. Run the database query using validated filters.
      5. Call Claude to explain the actual results (Step 3).
      6. Return a fully populated AIQueryResponse.

    This function NEVER raises.  All exceptions are caught and returned
    as user-facing messages so the endpoint always returns HTTP 200.

    Args:
        request : AIQueryRequest with the user's question.
        db      : Active SQLAlchemy session.

    Returns:
        AIQueryResponse — always a valid object.
    """

    # ------------------------------------------------------------------
    # Guard: AI unavailable
    # ------------------------------------------------------------------
    if not settings.anthropic_api_key:
        logger.warning("AI query attempted but ANTHROPIC_API_KEY is not set.")
        return AIQueryResponse(
            question         = request.question,
            intent_type      = "",
            detected_intent  = "",
            rejection_reason = None,
            filters_applied  = ExtractedFilters(),
            query_executed   = False,
            result_count     = 0,
            result_preview   = [],
            explanation      = (
                "The AI query layer is currently disabled. "
                "Set ANTHROPIC_API_KEY in your .env file to enable it. "
                "You can still use GET /api/v1/observations to filter data directly."
            ),
            ai_available     = False,
        )

    # ------------------------------------------------------------------
    # Step 1: Intent classification + filter extraction
    # ------------------------------------------------------------------
    try:
        intent_type, detected_intent, ai_rejection_reason, filters = (
            _classify_and_extract(request.question)
        )
    except Exception as exc:
        logger.error("AI extraction failed: %s", exc)
        return AIQueryResponse(
            question         = request.question,
            intent_type      = "rejected",
            detected_intent  = "",
            rejection_reason = f"The AI could not interpret your question: {exc}",
            filters_applied  = ExtractedFilters(),
            query_executed   = False,
            result_count     = 0,
            result_preview   = [],
            explanation      = (
                "The AI service encountered an error processing your question. "
                "Please try again or use GET /api/v1/observations directly."
            ),
            ai_available     = True,
        )

    logger.info(
        "AI extracted: intent=%s filters=%s",
        intent_type,
        filters.model_dump(exclude_none=True),
    )

    # ------------------------------------------------------------------
    # Step 2: Safety validation
    # ------------------------------------------------------------------
    is_valid, validation_rejection = _validate_intent_and_filters(intent_type, filters)

    # Merge AI rejection reason with our validation rejection reason
    final_rejection = ai_rejection_reason or validation_rejection

    if not is_valid:
        logger.info("Query rejected: %s", final_rejection)
        return AIQueryResponse(
            question         = request.question,
            intent_type      = "rejected",
            detected_intent  = detected_intent,
            rejection_reason = final_rejection,
            filters_applied  = filters,
            query_executed   = False,
            result_count     = 0,
            result_preview   = [],
            explanation      = (
                f"Your question could not be answered: {final_rejection} "
                if final_rejection else
                "Your question was too vague or is not supported. "
                "Try asking about a specific indicator, county, or year."
            ),
            ai_available     = True,
        )

    # ------------------------------------------------------------------
    # Step 3: Database query (using standard observation_service — no SQL)
    # ------------------------------------------------------------------
    try:
        total_count = count_observations(
            db             = db,
            dataset_name   = filters.dataset_name,
            indicator_name = filters.indicator_name,
            county         = filters.county,
            year_from      = filters.year_from,
            year_to        = filters.year_to,
        )

        preview_results = filter_observations(
            db             = db,
            dataset_name   = filters.dataset_name,
            indicator_name = filters.indicator_name,
            county         = filters.county,
            year_from      = filters.year_from,
            year_to        = filters.year_to,
            limit          = PREVIEW_LIMIT,
            offset         = 0,
        )

        logger.info(
            "AI query DB result: total=%d preview=%d",
            total_count,
            len(preview_results),
        )

    except Exception as exc:
        logger.error("Database query failed during AI query: %s", exc)
        return AIQueryResponse(
            question         = request.question,
            intent_type      = intent_type,
            detected_intent  = detected_intent,
            rejection_reason = None,
            filters_applied  = filters,
            query_executed   = False,
            result_count     = 0,
            result_preview   = [],
            explanation      = (
                "The database query failed unexpectedly. "
                "Please try again or contact support."
            ),
            ai_available     = True,
        )

    # ------------------------------------------------------------------
    # Step 4: Explanation (grounded in actual results)
    # ------------------------------------------------------------------
    explanation = _generate_explanation(
        question        = request.question,
        intent_type     = intent_type,
        detected_intent = detected_intent,
        filters         = filters,
        results         = preview_results,
        total_count     = total_count,
    )

    return AIQueryResponse(
        question         = request.question,
        intent_type      = intent_type,
        detected_intent  = detected_intent,
        rejection_reason = None,
        filters_applied  = filters,
        query_executed   = True,
        result_count     = total_count,
        result_preview   = preview_results,
        explanation      = explanation,
        ai_available     = True,
    )
