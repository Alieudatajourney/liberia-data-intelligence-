"""
backend/app/schemas/ai_query.py
==================================
Pydantic schemas for the AI-assisted natural language query endpoint.

Flow:
  1. Client sends a plain English question     →  AIQueryRequest
  2. AI classifies intent + extracts filters   →  (internal)
  3. Safety checks validate the filters        →  (internal)
  4. Backend executes the query                →  (internal)
  5. AI explains actual results                →  AIQueryResponse

Why two AI calls?
  The extraction call (step 2) runs BEFORE the database query.
  The explanation call (step 5) runs AFTER — it receives real result rows
  so it can only describe data that actually exists, preventing hallucination.

Response fields:
  intent_type      : classified intent — trend | comparison | summary | rejected
  detected_intent  : one-sentence description of what the AI understood
  rejection_reason : why the query was rejected (null if not rejected)
  filters_applied  : the structured filters derived from the question
  query_executed   : True if a database query was actually run
  result_count     : total matching rows (0 if query_executed=False)
  result_preview   : first N rows — real data only
  explanation      : plain-English description of the actual results
  ai_available     : False if ANTHROPIC_API_KEY is not set
"""

from typing import Literal
from pydantic import BaseModel, Field
from app.schemas.observation import ObservationExpanded


# ---------------------------------------------------------------------------
# Intent type
# ---------------------------------------------------------------------------

IntentType = Literal["trend", "comparison", "summary", "rejected", ""]
"""
  trend      — how one indicator changes over time in one county
  comparison — one indicator compared across counties in one year
  summary    — general lookup / summary query
  rejected   — vague, off-topic, or missing required parameters
  ""         — AI was not available (ai_available=False)
"""


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class AIQueryRequest(BaseModel):
    """
    A plain English question submitted by the user.

    Examples:
      "What is the total population of Nimba county?"
      "Compare employment rates across all counties in 2016."
      "How has malaria prevalence changed in Montserrado over time?"
    """

    question: str = Field(
        ...,
        min_length = 3,
        max_length = 500,
        description = "Plain English question about Liberia public data.",
        examples   = [
            "What is the total population of Nimba county?",
            "Show me employment rates by county in 2016.",
            "How has literacy changed in Lofa county?",
        ],
    )


# ---------------------------------------------------------------------------
# Filters extracted by the AI
# ---------------------------------------------------------------------------

class ExtractedFilters(BaseModel):
    """
    Structured query filters extracted from the natural language question.

    All fields are optional — the AI fills in only what it can confidently
    extract from the question.  Missing fields are left null.

    These filters are passed directly to the standard observation query
    using the same SQLAlchemy code as GET /observations.  The AI never
    touches the database directly.
    """

    dataset_name:   str | None = Field(default=None, description="Detected dataset name (partial).")
    indicator_name: str | None = Field(default=None, description="Detected indicator name (partial).")
    county:         str | None = Field(default=None, description="Detected county name.")
    year_from:      int | None = Field(default=None, description="Start year (if detected).")
    year_to:        int | None = Field(default=None, description="End year (if detected).")


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class AIQueryResponse(BaseModel):
    """
    Full response from the AI query endpoint.

    Always returns HTTP 200.  Check `ai_available` and `intent_type` to
    determine the response shape:

      ai_available=False   → AI is disabled; no query was run.
      intent_type=rejected → Question was rejected; no query was run.
      query_executed=True  → Database query ran; result_count and
                             result_preview contain real data.
    """

    # --- Original question ---
    question: str = Field(
        ...,
        description = "The original question, echoed back for reference.",
    )

    # --- Intent classification ---
    intent_type: str = Field(
        default    = "",
        description = (
            "Classified query intent: 'trend', 'comparison', 'summary', "
            "'rejected', or '' when AI is unavailable."
        ),
    )
    detected_intent: str = Field(
        ...,
        description = "One-sentence description of what the AI understood.",
        examples   = ["Trend query for Total Population in Nimba county across all years."],
    )
    rejection_reason: str | None = Field(
        default    = None,
        description = (
            "Why the query was rejected.  Null if intent_type is not 'rejected'. "
            "Examples: 'County name not recognized.', "
            "'Trend queries require both an indicator and a county.'"
        ),
    )

    # --- Filters ---
    filters_applied: ExtractedFilters = Field(
        ...,
        description = "The structured filters derived from the question.",
    )

    # --- Query execution ---
    query_executed: bool = Field(
        default    = False,
        description = (
            "True if a database query was actually executed. "
            "False if the query was rejected or AI is unavailable."
        ),
    )
    result_count: int = Field(
        ...,
        description = "Total number of matching observations found.",
        ge         = 0,
    )
    result_preview: list[ObservationExpanded] = Field(
        default_factory = list,
        description     = (
            "First 10 matching observations.  Always real data — never fabricated. "
            "Empty if query_executed=False or no results found."
        ),
    )

    # --- Explanation ---
    explanation: str = Field(
        ...,
        description = (
            "Plain-English summary of what the results show, "
            "generated from actual data after the query ran."
        ),
        examples   = ["Nimba county had a Total Population of 590,000 in 2008."],
    )

    # --- System status ---
    ai_available: bool = Field(
        default    = True,
        description = (
            "False if the AI layer is disabled (ANTHROPIC_API_KEY not set). "
            "When False, all other fields are empty/zero."
        ),
    )
