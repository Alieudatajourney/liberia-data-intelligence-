# CLAUDE.md — Project Rules & Working Agreement

## Project
**Liberia Public Data Intelligence** — indicator-based system for Liberia's public statistical datasets.
Stack: FastAPI + PostgreSQL + Pandas + Streamlit + Claude AI (optional).

---

## Architecture rules

- **Service layer pattern**: routes handle HTTP only; all DB/business logic lives in `backend/app/services/`
- **One service file per domain**: `dataset_service.py`, `indicator_service.py`, `county_service.py`, `observation_service.py`, `summary_service.py`
- `query_service.py` is a re-export facade — do not add logic there
- **AI never generates SQL** — structured intent classification only; county allowlist validation required
- **Two-call AI pattern**: extract intent/filters first, query DB second, explain results third
- Routes use `_route` suffix on function names to avoid shadowing service names

## Code rules

- Do not add features beyond what was asked
- Do not add docstrings or comments to code that wasn't changed
- Do not mock the database in tests — use SQLite via `app.dependency_overrides[get_db]`
- Keep responses concise — no trailing summaries after tool calls
- Never share or log API keys, tokens, or passwords

## Deployment

- Platform: **Railway** (switched from Heroku → Render → Fly.io → Railway)
- Railway project: `Intelligence`
- Project URL: https://railway.com/project/bad01a77-7dc9-445d-960d-4cd7bae25a14
- Backend service: `backend` (FastAPI, port 8000, gunicorn + uvicorn workers)
- Frontend service: `frontend` (Streamlit, port 8501)
- Database: Railway-managed PostgreSQL (online)
- `DATABASE_URL` is auto-injected by Railway from the linked Postgres service
- `ANTHROPIC_API_KEY` must be set manually in Railway dashboard (optional)
- `API_BASE_URL` must be set on the frontend service after backend is live

## Security rules

- Never put API keys or tokens in chat messages
- Revoke any key that was accidentally shared
- `data/raw/` is gitignored — never commit source Excel files
