# Liberia Public Data Intelligence

A unified, queryable intelligence layer for Liberia's public statistical datasets.

**This is an indicator-based system** — not a county-based system.

> Data sources include LISGIS (Liberia Institute of Statistics and Geo-Information Services),
> population and housing censuses, household surveys, and partner agency datasets.

---

## What it does

Raw Excel files from different government agencies arrive with inconsistent column
names, mixed formats, and varying structures. This system:

1. **Ingests** those files using per-dataset configuration
2. **Normalises** county names, years, and values into a consistent format
3. **Stores** every observation in a single unified table
4. **Exposes** the data through a REST API
5. **Visualises** it in an interactive Streamlit dashboard
6. **Answers** natural language questions using an AI query layer (optional)

The core data model is:

```
One observation = one indicator + one county + one year + (optional gender/age)
```

---

## Project structure

```
liberia-data-intelligence/
│
├── backend/                   Python + FastAPI backend
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes/        One file per feature area
│   │   │   │   └── health.py
│   │   │   └── router.py      Wires all routes together
│   │   ├── core/
│   │   │   ├── config.py      Reads settings from .env
│   │   │   └── logging_config.py
│   │   ├── db/
│   │   │   └── session.py     Database engine + session factory
│   │   ├── models/            ORM models (added in next phase)
│   │   ├── schemas/           Pydantic request/response schemas
│   │   ├── services/          Business logic layer
│   │   └── main.py            FastAPI app entry point
│   ├── scripts/               One-off utility scripts (init DB, seed data)
│   ├── tests/                 Automated tests
│   └── requirements.txt
│
├── frontend/
│   └── streamlit_app.py       Streamlit dashboard
│
├── data/
│   ├── raw/                   Source Excel files (gitignored)
│   ├── processed/             Intermediate outputs (gitignored)
│   └── sample/                Synthetic data for development
│
├── docs/                      Additional documentation
├── .env.example               Environment variable template
└── .gitignore
```

---

## Quick start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL running locally (or a connection string to a remote DB)

### 2. Clone and configure

```bash
cd liberia-data-intelligence

# Copy the environment template
cp .env.example .env

# Edit .env — at minimum, set DATABASE_URL
# Example: DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/liberia_data
```

### 3. Set up the backend

```bash
cd backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Create the database

Make sure PostgreSQL is running, then create the database:

```bash
psql -U postgres -c "CREATE DATABASE liberia_data;"
```

### 5. Run the backend

```bash
# From the backend/ directory
uvicorn app.main:app --reload --port 8000
```

Open in your browser:
- API docs (Swagger UI): http://localhost:8000/docs
- Liveness check:        http://localhost:8000/api/v1/health/
- DB connection check:   http://localhost:8000/api/v1/health/db

### 6. Run the frontend

```bash
# From the project root (liberia-data-intelligence/)
streamlit run frontend/streamlit_app.py
```

Open in your browser: http://localhost:8501

---

## Running tests

```bash
cd backend
pytest tests/ -v
```

---

## Environment variables

See `.env.example` for all available variables.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `APP_ENV` | No | `development` / `production` (default: `development`) |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` (default: `INFO`) |
| `API_BASE_URL` | No | Backend URL used by the dashboard (default: `http://localhost:8000`) |
| `ANTHROPIC_API_KEY` | No | Enables the AI natural language query endpoint |

---

## Development phases

| Phase | Status | Scope |
|---|---|---|
| 1 — Skeleton | ✅ Done | Project structure, config, health endpoint, dashboard shell |
| 2 — Schema | Next | ORM models: datasets, indicators, observations |
| 3 — Ingestion | Next | Config-driven Excel ingestor, normaliser |
| 4 — API | Next | /datasets, /indicators, /observations, /summary endpoints |
| 5 — Dashboard | Next | Filters, charts, data table, CSV export |
| 6 — AI layer | Later | Natural language → filters → results |

---

## Notes

- All data in `data/raw/` is gitignored. Keep source files out of version control.
- Verify all figures before use in policy documents or public reporting.
- The AI query layer requires an Anthropic API key and is fully optional.
