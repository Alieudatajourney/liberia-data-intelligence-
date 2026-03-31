"""
frontend/streamlit_app.py
==========================
Liberia Public Data Intelligence — Streamlit Dashboard

How to run (from the project root):
    streamlit run frontend/streamlit_app.py

The dashboard talks to the FastAPI backend.
Override the API address in .env:
    API_BASE_URL=http://your-server:8000

Data flow:
    Dataset → Indicator → Observation
    Choosing a dataset narrows which indicators are listed.
    Indicator + County + Year range narrow which observations load.
"""

import os
import json
import httpx
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

# ── Load .env from the project root (one level above /frontend) ────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── API configuration ──────────────────────────────────────────────────────
API_BASE_URL     = os.getenv("API_BASE_URL", "http://localhost:8000")
API_V1           = f"{API_BASE_URL}/api/v1"
REQUEST_TIMEOUT  = 10   # seconds for normal data requests
DOWNLOAD_TIMEOUT = 30   # seconds for CSV export (can be a large file)


# ============================================================
# Page setup — MUST be the first Streamlit call in the file
# ============================================================
st.set_page_config(
    page_title = "Liberia Data Intelligence",
    page_icon  = "🇱🇷",
    layout     = "wide",
)


# ============================================================
# API helper functions
# ============================================================
# Each function below calls one backend endpoint.
#
# @st.cache_data(ttl=N) tells Streamlit to remember the result
# for N seconds.  This avoids hammering the API every time the
# user clicks a filter — the cached result is reused instead.
#
# Functions that must NOT be cached (AI query, CSV download) are
# defined without the decorator so they always hit the backend.

@st.cache_data(ttl=60)
def fetch_datasets() -> list[dict]:
    """
    GET /datasets/ — return every dataset in the system.
    Each dataset is one source Excel file (e.g. "LISGIS Census 2008").
    """
    try:
        r = httpx.get(f"{API_V1}/datasets/", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_indicators(dataset_id: int | None = None) -> list[dict]:
    """
    GET /indicators/ — return all indicators, optionally narrowed
    to one dataset.  Cascades from the dataset selection.
    """
    params: dict = {}
    if dataset_id is not None:
        params["dataset_id"] = dataset_id
    try:
        r = httpx.get(f"{API_V1}/indicators/", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_counties() -> list[dict]:
    """GET /counties/ — return all counties (alphabetical)."""
    try:
        r = httpx.get(f"{API_V1}/counties/", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_summary() -> dict:
    """
    GET /summary/ — return overall statistics:
    total datasets, indicators, counties, observations, year range.
    """
    try:
        r = httpx.get(f"{API_V1}/summary/", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


@st.cache_data(ttl=30)
def fetch_observations(
    dataset_name:   str | None,
    indicator_name: str | None,
    county:         str | None,
    year_from:      int | None,
    year_to:        int | None,
    limit:          int = 500,
) -> list[dict]:
    """
    GET /observations/ — return filtered observations (up to `limit` rows).
    All parameters are optional — pass None to omit a filter.
    """
    params: dict = {"limit": limit}
    if dataset_name:   params["dataset_name"]   = dataset_name
    if indicator_name: params["indicator_name"] = indicator_name
    if county:         params["county"]          = county
    if year_from:      params["year_from"]       = year_from
    if year_to:        params["year_to"]         = year_to
    try:
        r = httpx.get(f"{API_V1}/observations/", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=30)
def fetch_trend(
    indicator_name: str,
    county:         str,
    dataset_name:   str | None = None,
    year_from:      int | None = None,
    year_to:        int | None = None,
) -> dict | None:
    """
    GET /summary/trend — return time-series for one indicator in one county.
    Returns None if no data exists for that combination (API sends 404).
    """
    params: dict = {"indicator_name": indicator_name, "county": county}
    if dataset_name: params["dataset_name"] = dataset_name
    if year_from:    params["year_from"]    = year_from
    if year_to:      params["year_to"]      = year_to
    try:
        r = httpx.get(f"{API_V1}/summary/trend", params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return None   # No data — handled gracefully in the UI
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=30)
def fetch_comparison(
    indicator_name: str,
    year:           int,
    dataset_name:   str | None = None,
) -> dict | None:
    """
    GET /summary/compare — return one indicator across all counties for one year.
    Returns None if no data exists (API sends 404).
    """
    params: dict = {"indicator_name": indicator_name, "year": year}
    if dataset_name: params["dataset_name"] = dataset_name
    try:
        r = httpx.get(f"{API_V1}/summary/compare", params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def send_ai_query(question: str) -> dict | None:
    """
    POST /ai/query — send a natural language question to the AI endpoint.
    NOT cached — always sends a live request.
    AI calls can be slow (~2–3 s), so this is called only when the
    user presses "Ask".
    """
    try:
        r = httpx.post(
            f"{API_V1}/ai/query",
            json    = {"question": question},
            timeout = 30,
        )
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        return {"_connect_error": True}
    except Exception as exc:
        return {"_error": str(exc)}


def fetch_csv_bytes(
    dataset_name:   str | None,
    indicator_name: str | None,
    county:         str | None,
    year_from:      int | None,
    year_to:        int | None,
) -> bytes | None:
    """
    GET /download/cleaned — fetch up to 50,000 filtered rows as CSV bytes.
    NOT cached — called only when the user clicks "Prepare CSV".
    """
    params: dict = {}
    if dataset_name:   params["dataset_name"]   = dataset_name
    if indicator_name: params["indicator_name"] = indicator_name
    if county:         params["county"]          = county
    if year_from:      params["year_from"]       = year_from
    if year_to:        params["year_to"]         = year_to
    try:
        r = httpx.get(
            f"{API_V1}/download/cleaned",
            params  = params,
            timeout = DOWNLOAD_TIMEOUT,
        )
        r.raise_for_status()
        return r.content   # raw UTF-8 bytes — passed directly to st.download_button
    except Exception:
        return None


# ============================================================
# Sidebar — cascading filter panel
# ============================================================
# The sidebar is the control panel for the whole dashboard.
# Filters cascade:  Dataset → Indicator → County + Year range
#
# Selecting a dataset narrows which indicators are shown.
# All four selections are passed to every data-fetching tab.

with st.sidebar:
    st.markdown("## 🇱🇷 Liberia Data")
    st.caption("Adjust the filters below to explore different slices of data.")
    st.divider()

    # ── Step 1: Dataset ───────────────────────────────────────────────
    # A dataset is one source file (e.g. "LISGIS Census 2008").
    # Picking one here narrows the indicator list in Step 2.
    st.markdown("**1 — Dataset**")
    datasets      = fetch_datasets()
    dataset_names = ["All datasets"] + [d["name"] for d in datasets]

    sel_dataset = st.selectbox(
        "Dataset",
        options     = dataset_names,
        label_visibility = "collapsed",
        help        = "Each dataset corresponds to one source file.",
    )

    # Translate the selection into values the API understands
    active_dataset_name = None if sel_dataset == "All datasets" else sel_dataset
    active_dataset_id   = None
    if active_dataset_name:
        match = next((d for d in datasets if d["name"] == active_dataset_name), None)
        if match:
            active_dataset_id = match["id"]

    st.divider()

    # ── Step 2: Indicator ─────────────────────────────────────────────
    # Indicators are scoped to a dataset.
    # If a dataset is selected in Step 1, only that dataset's indicators
    # appear here — keeping the list short and relevant.
    st.markdown("**2 — Indicator**")
    indicators      = fetch_indicators(dataset_id=active_dataset_id)
    indicator_names = ["All indicators"] + [i["name"] for i in indicators]

    sel_indicator = st.selectbox(
        "Indicator",
        options          = indicator_names,
        label_visibility = "collapsed",
        help             = (
            "An indicator is what is being measured — e.g. 'Total Population'. "
            "Select a dataset first to narrow this list."
        ),
    )
    active_indicator_name = None if sel_indicator == "All indicators" else sel_indicator

    st.divider()

    # ── Step 3: County ────────────────────────────────────────────────
    # Counties are global — not scoped to any dataset.
    st.markdown("**3 — County**")
    counties     = fetch_counties()
    county_names = ["All counties"] + [c["name"] for c in counties]

    sel_county = st.selectbox(
        "County",
        options          = county_names,
        label_visibility = "collapsed",
        help             = (
            "Liberia has 15 counties. "
            "'National' rows represent aggregate country-level figures."
        ),
    )
    active_county = None if sel_county == "All counties" else sel_county

    st.divider()

    # ── Step 4: Year range ────────────────────────────────────────────
    # Bounds are taken from the system summary so the slider always
    # matches what is actually in the database.
    st.markdown("**4 — Year range**")
    summary     = fetch_summary()
    data_yr_min = summary.get("year_min") or 1990
    data_yr_max = summary.get("year_max") or 2025

    year_range = st.slider(
        "Year range",
        min_value        = data_yr_min,
        max_value        = data_yr_max,
        value            = (data_yr_min, data_yr_max),
        label_visibility = "collapsed",
    )
    active_year_from, active_year_to = year_range

    st.divider()

    # ── Active filter summary ─────────────────────────────────────────
    # A quick read-out so the user can see exactly what is active.
    st.caption("Active filters")
    st.caption(f"Dataset   → **{sel_dataset}**")
    st.caption(f"Indicator → **{sel_indicator}**")
    st.caption(f"County    → **{sel_county}**")
    st.caption(f"Years     → **{active_year_from} – {active_year_to}**")


# ============================================================
# Page header
# ============================================================
st.title("🇱🇷 Liberia Public Data Intelligence")
st.markdown(
    "Unified access to standardised public statistics from LISGIS, "
    "national censuses, household surveys, and partner agencies. "
    "Use the **sidebar** to filter, then switch tabs to explore."
)

# ── Backend health banner ──────────────────────────────────────────────────
# Shown at the top so the user immediately knows if the backend is reachable.
try:
    _h = httpx.get(f"{API_V1}/health/", timeout=5).json()
    if _h.get("status") == "ok":
        st.success(
            f"Backend connected — "
            f"{_h.get('app', 'Liberia Data API')} "
            f"v{_h.get('version', '?')} [{_h.get('env', '?')}]",
            icon="✅",
        )
    else:
        st.warning("Backend is reachable but reported an unexpected status.")
except Exception:
    st.error(
        f"Cannot connect to the backend at `{API_BASE_URL}`. "
        "Start it with: `uvicorn app.main:app --reload` "
        "(run from the `backend/` directory).",
        icon="🔴",
    )

st.divider()


# ============================================================
# Main tabs
# ============================================================
(
    tab_overview,
    tab_trend,
    tab_compare,
    tab_table,
    tab_ai,
    tab_export,
) = st.tabs([
    "📊 Overview",
    "📈 Trend",
    "🗺️ Compare Counties",
    "🗃️ Data Table",
    "🤖 AI Query",
    "⬇️ Export",
])


# ────────────────────────────────────────────────────────────
# TAB 1  —  Overview
# High-level database statistics.  Good first stop to understand
# what data is loaded before diving into specific indicators.
# ────────────────────────────────────────────────────────────
with tab_overview:
    st.subheader("System Overview")
    st.caption("High-level statistics about the data currently loaded in the backend.")

    if not summary:
        st.warning(
            "Could not load the system summary. "
            "Make sure the backend is running and the database has been loaded.",
            icon="⚠️",
        )
    else:
        # ── Headline metrics ──────────────────────────────────────────
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Datasets",     f"{summary.get('total_datasets',     0):,}")
        c2.metric("Indicators",   f"{summary.get('total_indicators',   0):,}")
        c3.metric("Counties",     f"{summary.get('total_counties',     0):,}")
        c4.metric("Observations", f"{summary.get('total_observations', 0):,}")
        c5.metric(
            "Year range",
            f"{summary.get('year_min', '?')} – {summary.get('year_max', '?')}",
        )

        st.divider()

        # ── Per-dataset breakdown ─────────────────────────────────────
        st.markdown("#### Observations per dataset")
        st.caption("How many data points each source contributes to the system.")

        dataset_items = summary.get("datasets", [])
        if dataset_items:
            df_ds = pd.DataFrame(dataset_items).rename(columns={
                "dataset_name":      "Dataset",
                "observation_count": "Observations",
            })
            # Horizontal bar — better for reading long dataset names
            fig_ds = px.bar(
                df_ds,
                x                      = "Observations",
                y                      = "Dataset",
                orientation            = "h",
                color                  = "Observations",
                color_continuous_scale = "Blues",
                title                  = "Observation count by dataset",
            )
            fig_ds.update_layout(
                yaxis_title         = "",
                showlegend          = False,
                coloraxis_showscale = False,
                height              = max(250, len(df_ds) * 40),
            )
            st.plotly_chart(fig_ds, use_container_width=True)
        else:
            st.info(
                "No datasets loaded yet. "
                "Run `python scripts/load_db.py` to populate the database.",
                icon="ℹ️",
            )


# ────────────────────────────────────────────────────────────
# TAB 2  —  Trend (line chart)
# Shows how ONE indicator changes over time in ONE county.
# Requires both indicator and county to be selected in the sidebar.
# ────────────────────────────────────────────────────────────
with tab_trend:
    st.subheader("Trend Over Time")
    st.caption(
        "How one indicator changes year-by-year in one county.  "
        "Select both an **indicator** and a **county** in the sidebar."
    )

    # Both indicator and county are required — the API enforces this too.
    missing = []
    if not active_indicator_name: missing.append("indicator")
    if not active_county:         missing.append("county")

    if missing:
        st.info(
            f"Select a **{' and a '.join(missing)}** in the sidebar to see the trend chart.",
            icon="ℹ️",
        )
    else:
        trend_data = fetch_trend(
            indicator_name = active_indicator_name,
            county         = active_county,
            dataset_name   = active_dataset_name,
            year_from      = active_year_from,
            year_to        = active_year_to,
        )

        if trend_data is None:
            # 404 or connection error — show helpful guidance
            st.warning(
                f"No data found for **{active_indicator_name}** "
                f"in **{active_county}** ({active_year_from}–{active_year_to}). "
                "Try broadening the year range or selecting a different indicator.",
                icon="⚠️",
            )
        else:
            points = trend_data.get("points", [])
            unit   = trend_data.get("unit") or ""

            if not points:
                st.warning("The API returned an empty list of data points.")
            else:
                df_trend = pd.DataFrame(points)   # columns: year, value

                # Build axis label — include unit if available
                y_label  = active_indicator_name + (f" ({unit})" if unit else "")
                fig_line = px.line(
                    df_trend,
                    x       = "year",
                    y       = "value",
                    markers = True,
                    title   = (
                        f"{active_indicator_name} — {active_county} "
                        f"({active_year_from}–{active_year_to})"
                    ),
                    labels  = {"year": "Year", "value": y_label},
                )
                fig_line.update_traces(
                    line_color  = "#1f77b4",
                    line_width  = 2,
                    marker_size = 7,
                )
                # Show a tick for every year so gaps are visible
                fig_line.update_layout(
                    xaxis = dict(tickmode="linear", dtick=1),
                )
                st.plotly_chart(fig_line, use_container_width=True)

                # Raw data table — collapsed by default to keep the tab clean
                with st.expander("View raw data points"):
                    st.dataframe(
                        df_trend.rename(columns={"year": "Year", "value": y_label}),
                        use_container_width = True,
                        hide_index          = True,
                    )


# ────────────────────────────────────────────────────────────
# TAB 3  —  Compare Counties (horizontal bar chart)
# Shows ONE indicator across ALL counties for ONE year.
# Requires indicator from sidebar + year selected inside this tab.
# ────────────────────────────────────────────────────────────
with tab_compare:
    st.subheader("Compare Counties")
    st.caption(
        "One indicator's value across all counties for a chosen year.  "
        "Select an **indicator** in the sidebar, then pick a year below."
    )

    if not active_indicator_name:
        st.info(
            "Select an **indicator** in the sidebar to compare counties.",
            icon="ℹ️",
        )
    else:
        # Year selector — independent of the sidebar year range slider.
        # Uses a number_input so the user can type any year in range.
        compare_year = st.number_input(
            "Year to compare",
            min_value = data_yr_min,
            max_value = data_yr_max,
            value     = data_yr_max,
            step      = 1,
            help      = "Pick a single year to compare across all counties.",
        )

        comparison_data = fetch_comparison(
            indicator_name = active_indicator_name,
            year           = int(compare_year),
            dataset_name   = active_dataset_name,
        )

        if comparison_data is None:
            st.warning(
                f"No data found for **{active_indicator_name}** "
                f"in **{int(compare_year)}**. "
                "Try a different year or indicator.",
                icon="⚠️",
            )
        else:
            items = comparison_data.get("items", [])
            unit  = comparison_data.get("unit") or ""

            if not items:
                st.warning("The API returned no counties for this combination.")
            else:
                df_cmp = pd.DataFrame(items)   # columns: county, value
                # Drop rows where value is null — can't plot them
                df_cmp_clean = df_cmp.dropna(subset=["value"])

                if df_cmp_clean.empty:
                    st.warning(
                        "All values for this indicator and year are null. "
                        "Try a different year."
                    )
                else:
                    y_label = active_indicator_name + (f" ({unit})" if unit else "")

                    # Sort ascending so the longest bar is at the top
                    df_cmp_clean = df_cmp_clean.sort_values("value", ascending=True)

                    fig_bar = px.bar(
                        df_cmp_clean,
                        x                      = "value",
                        y                      = "county",
                        orientation            = "h",
                        title                  = (
                            f"{active_indicator_name} — all counties, {int(compare_year)}"
                        ),
                        labels                 = {"value": y_label, "county": "County"},
                        color                  = "value",
                        color_continuous_scale = "Teal",
                    )
                    fig_bar.update_layout(
                        yaxis_title         = "",
                        coloraxis_showscale = False,
                        showlegend          = False,
                        height              = max(350, len(df_cmp_clean) * 35),
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)

                    # Show if any counties had null values
                    null_counties = df_cmp[df_cmp["value"].isna()]["county"].tolist()
                    if null_counties:
                        st.caption(
                            f"Counties with no data for this year: "
                            f"{', '.join(null_counties)}"
                        )

                    with st.expander("View raw comparison data"):
                        st.dataframe(
                            df_cmp.sort_values("value", ascending=False).rename(
                                columns={"county": "County", "value": y_label}
                            ),
                            use_container_width = True,
                            hide_index          = True,
                        )


# ────────────────────────────────────────────────────────────
# TAB 4  —  Data Table
# Raw observations matching the sidebar filters.
# Paginated at 500 rows for fast loading.
# ────────────────────────────────────────────────────────────
with tab_table:
    st.subheader("Data Table")
    st.caption(
        "Raw observations matching the current sidebar filters.  "
        "Up to 500 rows shown here — use **Export** for larger extracts."
    )

    observations = fetch_observations(
        dataset_name   = active_dataset_name,
        indicator_name = active_indicator_name,
        county         = active_county,
        year_from      = active_year_from,
        year_to        = active_year_to,
        limit          = 500,
    )

    if not observations:
        st.info(
            "No observations match the current filters.  "
            "Try broadening your selections in the sidebar "
            "(e.g. choose 'All indicators' or widen the year range).",
            icon="ℹ️",
        )
    else:
        df_obs = pd.DataFrame(observations)

        # Display only the human-readable columns in a logical order
        col_order  = ["dataset_name", "indicator_name", "county", "year", "value"]
        col_labels = {
            "dataset_name":   "Dataset",
            "indicator_name": "Indicator",
            "county":         "County",
            "year":           "Year",
            "value":          "Value",
        }
        df_display = (
            df_obs[[c for c in col_order if c in df_obs.columns]]
            .rename(columns=col_labels)
        )

        st.caption(f"Showing **{len(df_display):,}** row(s).")
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Quick summary stats for the value column
        if "value" in df_obs.columns and df_obs["value"].notna().any():
            with st.expander("Value statistics"):
                val = df_obs["value"].dropna()
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Min",  f"{val.min():,.2f}")
                s2.metric("Max",  f"{val.max():,.2f}")
                s3.metric("Mean", f"{val.mean():,.2f}")
                s4.metric("Null rows", int(df_obs["value"].isna().sum()))


# ────────────────────────────────────────────────────────────
# TAB 5  —  AI Query
# Natural language interface to the data.
# The AI classifies the question, extracts filters, runs a
# standard DB query, then explains the real results.
# The AI never writes SQL and never invents numbers.
# ────────────────────────────────────────────────────────────
with tab_ai:
    st.subheader("AI-Assisted Query")
    st.markdown(
        "Ask a plain English question about Liberia's public data.  \n"
        "The AI interprets your question and runs a safe database query.  \n"
        "Results are always real data — the AI never invents numbers.\n\n"
        "**Supported question types:**\n"
        "- *Trend:* 'How has total population changed in Nimba county?'\n"
        "- *Compare:* 'Compare employment rates across all counties in 2016'\n"
        "- *Summary:* 'Show me health indicators for Montserrado'"
    )
    st.divider()

    # ── Input ─────────────────────────────────────────────────────────
    # We store the AI response in Streamlit's session_state so it
    # persists when the user switches tabs and comes back.
    if "ai_response" not in st.session_state:
        st.session_state.ai_response  = None
        st.session_state.ai_question  = ""

    question = st.text_input(
        "Your question",
        placeholder = "e.g. How has the literacy rate changed in Lofa county?",
        max_chars   = 500,
        key         = "ai_question_input",
        help        = (
            "Be specific: include an indicator name, county, and/or year. "
            "More specific questions get better answers."
        ),
    )

    col_ask, col_clear = st.columns([1, 5])
    with col_ask:
        ask_clicked = st.button(
            "Ask",
            type     = "primary",
            disabled = not (question or "").strip(),
        )
    with col_clear:
        if st.button("Clear", type="secondary"):
            st.session_state.ai_response = None
            st.session_state.ai_question = ""
            st.rerun()

    # ── Call the API when Ask is clicked ──────────────────────────────
    if ask_clicked and (question or "").strip():
        st.session_state.ai_question = question.strip()
        with st.spinner("Thinking — this takes a few seconds..."):
            st.session_state.ai_response = send_ai_query(question.strip())

    # ── Render the response ───────────────────────────────────────────
    resp = st.session_state.ai_response

    if resp is None:
        # Nothing asked yet — show guidance
        st.info(
            "Type a question above and click **Ask**.",
            icon="💬",
        )

    elif resp.get("_connect_error"):
        st.error(
            "Cannot reach the backend. "
            "Make sure the API is running before using the AI query.",
            icon="🔴",
        )

    elif resp.get("_error"):
        st.error(f"Request failed: {resp['_error']}", icon="🔴")

    elif not resp.get("ai_available", True):
        # API key not configured
        st.warning(
            "The AI layer is disabled.  "
            "Set `ANTHROPIC_API_KEY` in your `.env` file to enable it.",
            icon="⚠️",
        )
        st.info(
            "You can still explore data using the sidebar filters and the "
            "Trend, Compare Counties, and Data Table tabs."
        )

    else:
        # We have a real AI response — render it in sections.
        intent_type      = resp.get("intent_type", "")
        detected_intent  = resp.get("detected_intent", "")
        rejection_reason = resp.get("rejection_reason")
        filters_applied  = resp.get("filters_applied", {})
        query_executed   = resp.get("query_executed", False)
        result_count     = resp.get("result_count", 0)
        result_preview   = resp.get("result_preview", [])
        explanation      = resp.get("explanation", "")

        # ── Intent badge ──────────────────────────────────────────────
        # Visual indicator of what the AI thought you were asking for.
        badge = {
            "trend":      ("🔵", "Trend query"),
            "comparison": ("🟢", "Comparison query"),
            "summary":    ("🟡", "Summary query"),
            "rejected":   ("🔴", "Rejected"),
        }.get(intent_type, ("⚪", intent_type or "Unknown"))

        st.markdown(f"**Intent:** {badge[0]} {badge[1]}")
        if detected_intent:
            st.caption(detected_intent)

        # ── Rejected or no query run ──────────────────────────────────
        if not query_executed:
            st.warning(
                rejection_reason
                or "Your question was not specific enough to run a query.",
                icon="⚠️",
            )
            st.markdown(
                "**Tips for better results:**\n"
                "- Name a specific indicator (e.g. 'total population', 'literacy rate')\n"
                "- Name a specific county (e.g. 'in Nimba', 'for Montserrado')\n"
                "- For trend queries: include a county\n"
                "- For comparison queries: include a year (e.g. 'in 2016')"
            )

        else:
            # ── Filters the AI applied ────────────────────────────────
            # Shown in an expander to keep the UI clean.
            with st.expander("Filters applied by the AI"):
                active_filters = {
                    k: v for k, v in filters_applied.items() if v is not None
                }
                if active_filters:
                    for k, v in active_filters.items():
                        # Format key from snake_case to Title Case
                        label = k.replace("_", " ").title()
                        st.caption(f"• **{label}:** {v}")
                else:
                    st.caption("No specific filters were extracted.")

            st.divider()

            # ── Explanation ───────────────────────────────────────────
            # Generated AFTER the query ran, from real result rows.
            st.markdown("**What the data shows:**")
            st.write(explanation)

            # ── Result preview ────────────────────────────────────────
            st.caption(f"Total matching observations: **{result_count:,}**")

            if result_preview:
                df_preview   = pd.DataFrame(result_preview)
                preview_cols = ["dataset_name", "indicator_name", "county", "year", "value"]
                df_preview   = (
                    df_preview[[c for c in preview_cols if c in df_preview.columns]]
                    .rename(columns={
                        "dataset_name":   "Dataset",
                        "indicator_name": "Indicator",
                        "county":         "County",
                        "year":           "Year",
                        "value":          "Value",
                    })
                )
                st.dataframe(df_preview, use_container_width=True, hide_index=True)

                if result_count > len(result_preview):
                    st.caption(
                        f"Showing {len(result_preview)} preview rows of "
                        f"{result_count:,} total.  "
                        "Use the sidebar filters + **Data Table** tab to explore the full set."
                    )
            else:
                # Query ran but returned zero rows
                st.info(
                    "No observations matched the extracted filters.  "
                    "Try rephrasing or use the sidebar to browse manually.",
                    icon="ℹ️",
                )


# ────────────────────────────────────────────────────────────
# TAB 6  —  Export
# Downloads filtered data as a CSV file from the backend.
# The API enforces a 50,000 row cap on CSV exports.
# ────────────────────────────────────────────────────────────
with tab_export:
    st.subheader("Export Data")
    st.caption(
        "Download filtered observations as a CSV file.  "
        "The backend exports up to **50,000 rows** per request."
    )

    # ── Show the active filters so the user knows what they'll get ────
    st.markdown("**Export will use these filters:**")
    fa, fb = st.columns(2)
    with fa:
        st.markdown(f"- Dataset &nbsp;&nbsp;: **{sel_dataset}**")
        st.markdown(f"- Indicator : **{sel_indicator}**")
    with fb:
        st.markdown(f"- County &nbsp;&nbsp;&nbsp;: **{sel_county}**")
        st.markdown(f"- Years &nbsp;&nbsp;&nbsp;&nbsp;: **{active_year_from} – {active_year_to}**")

    st.divider()

    # ── Prepare step ──────────────────────────────────────────────────
    # Streamlit's download_button needs the file content ready before
    # the button is rendered.  We fetch the CSV into session_state when
    # "Prepare CSV" is clicked, then show the real download button.
    if "csv_content"   not in st.session_state: st.session_state.csv_content   = None
    if "csv_row_count" not in st.session_state: st.session_state.csv_row_count = 0

    # Reset the cached CSV if any filter has changed since last prepare
    filter_key = (
        active_dataset_name, active_indicator_name,
        active_county, active_year_from, active_year_to,
    )
    if "last_export_filters" not in st.session_state:
        st.session_state.last_export_filters = None

    if st.session_state.last_export_filters != filter_key:
        # Filters changed — clear old CSV so the user re-prepares
        st.session_state.csv_content          = None
        st.session_state.csv_row_count        = 0
        st.session_state.last_export_filters  = filter_key

    prepare_col, _ = st.columns([1, 4])
    with prepare_col:
        if st.button(
            "Prepare CSV",
            help = (
                "Fetches the filtered data from the backend.  "
                "This may take a moment for large extracts."
            ),
        ):
            with st.spinner("Fetching data from the backend..."):
                csv_bytes = fetch_csv_bytes(
                    dataset_name   = active_dataset_name,
                    indicator_name = active_indicator_name,
                    county         = active_county,
                    year_from      = active_year_from,
                    year_to        = active_year_to,
                )

            if csv_bytes:
                st.session_state.csv_content = csv_bytes
                # Count rows: number of newlines minus 1 (for header)
                st.session_state.csv_row_count = max(0, csv_bytes.count(b"\n") - 1)
                st.success(
                    f"Ready — {st.session_state.csv_row_count:,} row(s) prepared.",
                    icon="✅",
                )
            else:
                st.error(
                    "Could not fetch data from the backend.  "
                    "Check the backend is running and your filters return data.",
                    icon="🔴",
                )
                st.session_state.csv_content = None

    # ── Download button ───────────────────────────────────────────────
    # Only shown once Prepare has been clicked and succeeded.
    if st.session_state.csv_content:
        st.download_button(
            label     = f"⬇️  Download CSV ({st.session_state.csv_row_count:,} rows)",
            data      = st.session_state.csv_content,
            file_name = "liberia_observations.csv",
            mime      = "text/csv",
        )
        st.caption(
            "CSV columns: `dataset_name`, `indicator_name`, `county`, `year`, `value`."
        )
    else:
        st.info(
            "Click **Prepare CSV** above to generate the download file.",
            icon="ℹ️",
        )


# ============================================================
# Footer
# ============================================================
st.divider()
st.caption(
    "Data sourced from LISGIS and partner agencies. "
    "Verify all figures before use in policy or reporting.  "
    f"API: `{API_BASE_URL}`"
)
