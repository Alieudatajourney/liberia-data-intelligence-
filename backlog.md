# backlog.md — Everything Still Left To Do

## In Progress
- [ ] Deploy backend to Railway (`railway up` from backend/, select `backend` service)

---

## Deployment (immediate)
- [ ] Verify `DATABASE_URL` is auto-linked on backend service
- [ ] Set `ANTHROPIC_API_KEY` secret on backend service in Railway dashboard
- [ ] Run `python scripts/init_db.py` via Railway shell to create DB tables
- [ ] Deploy frontend to Railway (`railway up` from frontend/, select `frontend` service)
- [ ] Set `API_BASE_URL` on frontend service = live backend URL
- [ ] Smoke test: hit `/api/v1/health/` and `/api/v1/health/db` on live backend
- [ ] Smoke test: open live Streamlit dashboard in browser

---

## GitHub (blocked — needs new PAT)
- [ ] Generate new Personal Access Token at github.com/settings/tokens (classic, `repo` scope)
- [ ] Push code: `git push -u origin main` from project root (use token as password, never paste in chat)

---

## Data loading
- [ ] Obtain real Excel files from LISGIS / partner agencies
- [ ] Place files in `data/raw/` (gitignored)
- [ ] Run ingestion scripts to populate the database
- [ ] Verify data appears in dashboard

---

## Testing
- [ ] Run full test suite: `cd backend && pytest tests/ -v`
- [ ] Fix any failing tests
- [ ] Add test for AI query service (`test_ai_query.py`)

---

## Future features (not started)
- [ ] User authentication / access control
- [ ] Admin panel for uploading new datasets
- [ ] Scheduled data refresh (cron)
- [ ] Data export to PDF report
- [ ] Map visualisation (county choropleth)
- [ ] Multi-language support (English + local languages)
- [ ] API rate limiting
- [ ] Audit log for AI queries

---

## Done
- [x] Project skeleton (FastAPI, config, health endpoint)
- [x] ORM models (Dataset, Indicator, County, Observation)
- [x] Ingestion pipeline (config-driven Excel ingestor + normaliser)
- [x] Service layer (5 service files)
- [x] REST API routes (/datasets, /indicators, /counties, /observations, /summary, /download)
- [x] Safe AI query system (intent classification, no SQL generation, county allowlist)
- [x] Streamlit dashboard (6 tabs: Overview, Trend, Compare, Data Table, AI Query, Export)
- [x] Pytest tests (test_health, test_observations, test_cleaning, test_ingestion)
- [x] Dockerfiles (backend + frontend)
- [x] fly.toml files (backend + frontend) — kept, not used
- [x] render.yaml — kept, not used
- [x] Railway project created + PostgreSQL online
