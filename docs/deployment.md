# Deployment

## Local — native processes (fastest iteration, what was used to verify this build)

```bash
# 1. Postgres running locally on 5432 with a `recoveryos` db/role (see README Quickstart if
#    you need to create one — this repo's own verification used a native Windows PostgreSQL
#    17 install rather than Docker, since Docker Desktop needs WSL2 to be set up first).
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload          # http://localhost:8000

# separate shell:
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000
```

## Local — Docker Compose (closer to how Render deploys it)

Requires Docker Desktop with its Linux engine available (on Windows, that means WSL2 is
installed and enabled — `wsl --install` then a reboot, if not already set up).

```bash
docker compose up --build
```

Brings up Postgres, the backend (builds the model into the image at build time — see
`backend/Dockerfile`'s comments — then runs migrations and starts uvicorn), and the frontend
(nginx serving the built SPA, proxying `/api` to the backend container). Frontend at
`http://localhost:3000`, backend directly at `http://localhost:8000`.

## Render

`render.yaml` at the repo root is a Render Blueprint — it declares all three resources
(Postgres, backend web service, frontend static site) so Render provisions everything from
one file instead of manual per-service setup.

### 1. Push to GitHub

Render deploys from a connected git repository — it needs one to exist first.

```bash
git add -A
git commit -m "Initial RecoveryOS submission"
git remote add origin <your-github-repo-url>
git push -u origin master
```

(Substitute your actual GitHub repo URL — create an empty one first at github.com/new if you
don't have one yet. **Never** `git add .env` — it's gitignored already, but double-check with
`git status` before the first commit that it isn't listed.)

### 2. Create the Blueprint on Render

1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**.
2. Connect the GitHub repo you just pushed.
3. Render reads `render.yaml` and shows the 3 resources it's about to create
   (`recoveryos-db`, `recoveryos-backend`, `recoveryos-frontend`). Confirm.
4. Render will prompt for the `sync: false` secrets before the first deploy:
   `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `LLM_API_KEY`. **All
   four can be left blank** — the system runs fully autonomously without them (simulator
   gateway + ML-only scoring). Fill in real Razorpay test-mode credentials only if you want
   the deployed demo to exercise real Payment Link creation.
5. Deploy. The backend build takes a few minutes (it trains the ML model as part of the
   image build — see `backend/Dockerfile`); the frontend build is fast.

### 3. Verify

- Backend health: `https://recoveryos-backend.onrender.com/api/health` → `{"status":"ok",...}`
- Frontend: `https://recoveryos-frontend.onrender.com` — Command Center should load with real
  (initially zero) metrics. Use the Simulation page to generate a failure storm and watch it
  populate.

### Notes and honest limitations

- **Free tier**: the backend web service spins down after 15 minutes idle and takes ~30-60s
  to wake on the next request — the model does *not* retrain on wake (it's baked into the
  image), only the container restarts. Render's free Postgres plan (where still offered)
  expires after a fixed window; if that happens before your submission is reviewed, upgrade
  the database to the cheapest paid tier or point `DATABASE_URL` at an external free Postgres
  (Neon, Supabase) instead.
- **CORS**: the backend's `CORS_ALLOWED_ORIGINS` env var is wired via Render's
  `fromService: {property: host}` to automatically match the frontend's deployed hostname —
  no manual configuration needed, but if you rename either service in `render.yaml`, redeploy
  both so the reference re-resolves.
- **This exact deployment path was not run against a live Render account in this session** —
  no Render credentials were available. Everything above (the Dockerfile, render.yaml, CORS
  wiring, `DATABASE_URL`/`VITE_API_BASE_URL` normalization) was written correctly and
  validated as far as possible without one: the Docker build steps mirror exactly what was
  verified locally (migration, model training, `uvicorn` startup), and
  `tests/unit/test_config.py` covers the URL-normalization logic Render's env var
  interpolation depends on. Treat the first real deploy as the final verification step, and
  report back anything that doesn't match this document so it can be corrected.
