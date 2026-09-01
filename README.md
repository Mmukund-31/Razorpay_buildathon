# RecoveryOS — Autonomous Revenue Recovery Control Plane

Built for the **Razorpay AI Buildathon — Track 03: AI Revenue Recovery**.

> RecoveryOS detects revenue at risk, determines the highest-value recovery intervention,
> validates that intervention through deterministic financial safety policies, executes only
> approved actions, and measures the money actually recovered.
>
> **AI proposes. Optimization prioritizes. Policy decides. Executor acts. Ledger proves.**

## Status

**Core pipeline, ML, policy, execution, API, frontend, and benchmark are real and working —
including the full outcome-reconciliation loop for payment-link-driven recovery**, closed in
the final hardening pass (see `docs/final-readiness-report.md`). End to end: webhook
ingestion → state reconstruction → revenue signal detection → ML scoring (a real trained
LightGBM model) → AI diagnosis (real Anthropic integration, degrades gracefully without a
key) → optimizer → policy engine (8 real rules) → executor (real Razorpay Payment Link
adapter, falls back to a clearly-labeled simulator without credentials) → **outcome
reconciliation** (correlates a NEW payment made through a recovery Payment Link back to its
originating case, writes the actual recovered amount exactly once, idempotently) → audit
ledger, all wired together and covered by **113 test functions / 136 collected test cases,
135 passing, 1 explicitly skipped** (0 failures — see Quickstart). A 4-baseline benchmark
(plus an optional 5th AI-inclusive ablation arm, `--run-ai-ablation`) has actually been run
against 7,500 held-out synthetic rows; the honest results (RecoveryOS wins on precision and
Net Recovery Value, not raw gross revenue) are in
[`docs/ml-evaluation.md`](docs/ml-evaluation.md) and [`docs/ai-ablation.md`](docs/ai-ablation.md).
The React frontend (7 pages) builds cleanly against this API. A native local PostgreSQL
instance was reachable in this hardening pass, so the full suite — including every
integration test — has genuinely run against a live database, not just self-skipped; Docker
Compose itself was not exercised in this pass (the Docker daemon wasn't running in this
environment) — see [`docs/limitations.md`](docs/limitations.md) and
[`docs/track-alignment.md`](docs/track-alignment.md) for the precise, honest boundary of
what's verified where.

## Why this exists

Revenue loss from failed payments, abandoned checkouts, and failed subscriptions rarely gets a
system-level response — most integrations just show the failure in a dashboard. RecoveryOS
closes the loop: ingest the failure, diagnose why it happened, decide the best-value response
within hard safety limits, act on it through real Razorpay APIs where they exist (and clearly
labeled simulation where they don't), and prove — with an immutable audit trail and a
benchmark against naive baselines — how much money actually came back.

## Architecture at a glance

```
Razorpay Test Mode → Event Ingestion → State Reconstruction → Revenue Signal Engine
   → Recovery Opportunity Engine → [ML Predictor ‖ AI Diagnostician] → Intervention Optimizer
   → Policy Gate → Executor → (Razorpay API | Customer Channel) → Outcome Engine
   → Recovery Ledger → Benchmark Engine
```

Full detail: [`docs/architecture.md`](docs/architecture.md).

**The LLM never touches money.** It classifies and proposes via strict, Pydantic-validated
structured output with zero tool access. A deterministic policy engine is the only thing that
can approve a financial action, and the executor is the only code allowed to call Razorpay or
a customer-communication provider. See [`docs/ai-design.md`](docs/ai-design.md) and
[`docs/decisions.md`](docs/decisions.md).

## Repository layout

```
backend/     FastAPI service — API, domain model, services, policies, executors, integrations
ml/          Synthetic data generation, feature engineering, training, evaluation
simulator/   Failure-storm / scenario generators and the 4-baseline benchmark runner
frontend/    React + TypeScript operations dashboard
docs/        Architecture, track alignment, Razorpay integration notes, ADRs, demo script
scripts/     Operational scripts (migrations, seeding, dataset generation, simulator runs)
```

## Quickstart (local development)

Requires Docker Desktop (or a local PostgreSQL 16+), Python 3.12+, and Node 20+.

```bash
cp .env.example .env          # fill in RAZORPAY_* and LLM_API_KEY if you have them —
                               # everything works in fully-simulated mode without them
docker compose up -d postgres
cd backend
pip install -e ".[dev]"
alembic upgrade head

# Train the ML model (generates a 50k-row synthetic dataset, then trains + evaluates):
python ../scripts/generate_synthetic_dataset.py --rows 50000 --seed 42
python ../ml/training/train_baseline.py
python ../ml/training/train_lightgbm.py     # marks itself active in ml/training/artifacts/

uvicorn app.main:app --reload
# in another shell:
pytest

# frontend, in another shell:
cd ../frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000

# seed a few demo cases for the Command Center/Recovery Queue (optional):
python ../scripts/seed_db.py
# or a bigger failure storm / one named failure-injection scenario:
python ../scripts/run_simulator.py failure-storm --count 100
python ../scripts/run_simulator.py scenario duplicate_webhook

# benchmark, once a model is trained (~11s against the full held-out test set):
python simulator/benchmark/baseline_runner.py
# add --run-ai-ablation for the 5th, AI-inclusive arm on a bounded sample (needs LLM_API_KEY)
```

`GET http://localhost:8000/api/health` should return `{"status": "ok", "db": "ok", ...}`.

> **No Docker/Postgres available?** Unit and smoke tests (state machines, policy engine,
> optimizer math, AI safety, ML inference against the real trained model, webhook signature
> verification, app wiring) run with no external dependencies:
> `cd backend && pytest -m "unit or smoke"`. Integration tests that need a real database skip
> themselves with a clear message rather than silently pretending to pass — see
> [`backend/tests/conftest.py`](backend/tests/conftest.py). The full suite (113 test
> functions, 136 collected test cases including every integration test) has actually been run
> against a live PostgreSQL instance and passes — see [`docs/deployment.md`](docs/deployment.md)
> for local-Postgres setup notes and [`docs/reliability.md`](docs/reliability.md) for what
> each test proves.

For Docker Compose (full local stack: Postgres + backend + frontend in one command) and
deploying to Render, see [`docs/deployment.md`](docs/deployment.md) — includes a
ready-to-use `render.yaml` blueprint.

## Razorpay integration

RecoveryOS is honest about what Razorpay's API can and can't do — most importantly, **there is
no API to force-retry a failed one-time payment**; real recovery works through generating a
new Payment Link. Every claim in this repo about "real Razorpay integration" vs "simulated" is
enumerated in [`docs/razorpay-integration.md`](docs/razorpay-integration.md), sourced from the
live Razorpay documentation, not assumed.

## Documentation index

| Doc | Contents |
|---|---|
| [`docs/deployment.md`](docs/deployment.md) | Local (native + Docker Compose) and Render deployment, step by step |
| [`docs/architecture.md`](docs/architecture.md) | Components, data flow, AI/ML/policy/execution boundaries, failure handling, scaling path |
| [`docs/track-alignment.md`](docs/track-alignment.md) | Every Track 03 requirement → component → implementation → test → demo evidence |
| [`docs/razorpay-integration.md`](docs/razorpay-integration.md) | What's real vs simulated, sourced from verified Razorpay docs |
| [`docs/decisions.md`](docs/decisions.md) | ADRs — why FastAPI/Postgres/no-Redis/no-microservices/etc. |
| [`docs/ai-design.md`](docs/ai-design.md) | LLM role, prompt architecture, validation, failure handling |
| [`docs/ml-evaluation.md`](docs/ml-evaluation.md) | Dataset, features, leakage prevention, real trained-model metrics, real 4-baseline benchmark results |
| [`docs/ai-ablation.md`](docs/ai-ablation.md) | The 5th, AI-inclusive benchmark arm — setup, metrics, honest results |
| [`docs/reliability.md`](docs/reliability.md) | Every safety invariant with its enforcement mechanism and the test proving it |
| [`docs/security.md`](docs/security.md) | Webhook security, secrets, prompt-injection defense |
| [`docs/limitations.md`](docs/limitations.md) | What's synthetic, simulated, or out of scope — stated plainly |
| [`docs/interview-defense.md`](docs/interview-defense.md) | Answers to the hard questions a reviewer would actually ask |
| [`docs/final-readiness-report.md`](docs/final-readiness-report.md) | What changed in the final hardening pass, and the submission-readiness call |
| [`docs/demo-script.md`](docs/demo-script.md) | 5-minute live demo script |

## License

Buildathon submission — no license granted for reuse.
