# Known Limitations

Stated plainly, per this project's own "no fabricated metrics, no hidden gaps" convention.

## Data and evaluation

- **The ML training/benchmark dataset is entirely synthetic**
  (`ml/data/synthetic_generator.py`), not real merchant transaction history. The generating
  function's `true_recovery_probability()` is hand-authored; it's a reasonable model of how
  failure class, retry count, customer history, and intervention type plausibly interact, but
  it is not fit to or validated against real-world outcomes. Every benchmark number in
  `docs/ml-evaluation.md`/`docs/ai-ablation.md` should be read as "what this decision logic
  does against a known, controlled synthetic world," not as a production recovery-rate
  forecast.
- **The train/validation/test split is by row, not by customer**
  (`docs/ml-evaluation.md`'s own disclosed caveat) — a soft form of leakage, since the same
  synthetic customer's other events can land in a different split.
- **The AI-ablation arm (`RECOVERYOS_AI`) was not executed against a live LLM** in this
  hardening pass — no `LLM_API_KEY` was configured, and per an explicit scope decision for
  this pass, no real Anthropic API calls were made. The code path is real, unit-tested with a
  mocked diagnostician, and ready to run; see `docs/ai-ablation.md` for exactly what would
  change once a key is configured.
- **Net Recovery Value is computed from *expected*, not *realized*, recovered revenue** for
  every baseline — a baseline with poorly-calibrated probabilities (ML_ONLY, ECE ≈0.26 on the
  last run) can show a Net Recovery Value far higher than its actual recovered revenue. This
  is disclosed explicitly in `docs/ml-evaluation.md`, not smoothed over.

## Razorpay integration

- **Live Razorpay Test Mode execution was not performed** in this hardening pass — no
  `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` were configured, and per the same scope decision, no
  live Test Mode calls were made. Every adapter (`payment_link_adapter.py`,
  `subscription_adapter.py`) is implemented against the verified real API shape
  (`docs/razorpay-integration.md`) and is exercised in tests via `respx`-mocked HTTP, never a
  hand-waved stub — but a genuine end-to-end Test Mode payment (create a real test-mode
  Payment Link, pay it via Razorpay's mock bank page, receive the real webhook) has not been
  run against a live Razorpay account.
- **Plain `payment.captured` events with no `payment_link` entity carry no recovery
  correlation information at all.** If a merchant's webhook configuration doesn't include
  `payment_link.paid`, a payment made through a recovery Payment Link cannot be traced back to
  its originating case — the payment itself is still reconstructed correctly, but
  `outcome_service.reconcile_outcome()` has nothing to match it against. This is a real gap in
  that specific (avoidable, by subscribing to the right webhook events) configuration, not a
  silently swallowed failure — see `docs/razorpay-integration.md` §10.
- **Partial payments on Payment Links are not specially handled.** Razorpay Payment Links
  natively support partial payment; `reconcile_outcome()` currently treats any captured amount
  as fully resolving the case rather than branching on `amount < case.amount`. Not exercised
  or tested in this pass — a real gap if partial-payment recovery matters for a given
  deployment.

## Subscriptions

- **Subscription recovery is a real but partial extension, not a fully supported workflow**
  (already honestly scoped in `docs/track-alignment.md` before this hardening pass, and left
  that way). The real merchant-side levers (`subscription_card_change`,
  invoice charging) are implemented and tested; `revenue_signal_service.py`/
  `razorpay_payload_parser.py` do not parse `subscription.*` webhook events, so subscription
  opportunities aren't auto-created by the autonomous pipeline. The primary, fully supported
  workflow is one-time payment failure → recovery.

## Infrastructure and reproducibility

- **Docker Compose was not exercised end-to-end in this hardening pass** — the Docker daemon
  was not running in this environment (Docker Desktop needs setup this machine didn't have
  configured). `alembic upgrade head`, the full test suite, the ML training pipeline, and the
  benchmark were all verified against a real, reachable PostgreSQL instance (a native Windows
  Postgres 17 service, not Docker), and Docker Compose's configuration (healthchecks, startup
  ordering, migration-at-container-start) was reviewed but not run.
- **Render deployment was not exercised** — no live Render account/credentials were available.
  `render.yaml` and the Dockerfiles are written and reviewed, not independently verified
  end-to-end (already disclosed in `docs/deployment.md`).

## AI and voice

- **The Hinglish voice channel is a simulation** (`SimulatedVoiceProvider`), not real
  telephony — clearly labeled as such everywhere it appears (UI, docs, demo script), never
  implied to be a real call. It still passes through the full consent → policy → executor →
  audit path; only the actual phone call is simulated.
- **LLM calls are not temperature-pinned** (`ai_diagnostician._call_llm` doesn't set
  `temperature`), so re-running the same case through a live model will not produce
  byte-identical diagnosis text — a reproducibility caveat for the AI ablation study, not a
  correctness issue (structured output validation and the bounded EV nudge don't depend on
  exact wording).

## Scale

- This is a buildathon-scale build: single-process FastAPI + one Postgres instance + a
  DB-polling background worker (deliberately, not Kafka/Redis — see `docs/decisions.md`
  ADR-002). It has not been load-tested, and no claim is made about production-scale webhook
  throughput. The architecture's scaling path (more worker instances, `SELECT ... FOR UPDATE
  SKIP LOCKED` already making that safe) is documented in `docs/architecture.md`, not
  implemented at scale.
