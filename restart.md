# restart.md — Where We Stopped

## Last updated: 2026-03-31

## What we were doing
Deploying the app to **Railway** after trying Heroku (misbehaving), Render (GitHub auth issues), and Fly.io (requires credit card).

## Exact stopping point
1. Railway CLI installed (v4.35.1) and logged in as Alieu S Keita
2. Railway project **Intelligence** created: https://railway.com/project/bad01a77-7dc9-445d-960d-4cd7bae25a14
3. PostgreSQL database added via dashboard — **online**
4. Empty service named `backend` created in Railway dashboard
5. **Next command to run:**
   ```bash
   cd /Users/apple/Downloads/LIB/liberia-data-intelligence/backend
   railway up
   ```
   → When prompted "Select a service", choose **backend**

## After backend deploys
1. Get backend URL from Railway dashboard (e.g. `https://backend.up.railway.app`)
2. Set env vars on backend service:
   - `DATABASE_URL` — auto-linked from Postgres (verify it's there)
   - `ANTHROPIC_API_KEY` — set manually in Railway dashboard (optional)
3. Run DB init: Railway dashboard → backend service → Shell → `python scripts/init_db.py`
4. Create frontend service in Railway dashboard (empty service, name it `frontend`)
5. Deploy frontend:
   ```bash
   cd /Users/apple/Downloads/LIB/liberia-data-intelligence/frontend
   railway up
   ```
   → Select service: **frontend**
6. Set `API_BASE_URL` on frontend service = backend URL from step 1

## Known issues
- GitHub push still pending (need new Personal Access Token — generate at github.com/settings/tokens, use in terminal only, never paste in chat)
- `railway add` CLI command for databases fails with "Unauthorized" — use dashboard instead
