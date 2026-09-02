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
- **The `RECOVERYOS_AI` benchmark arm requires a live `LLM_API_KEY` with available credit** to
  produce real numbers — the mechanism itself (the nudge arithmetic, failure handling, circuit
  breaker) is real and unit-tested with a mocked diagnostician; see `docs/ai-ablation.md` for
  what's verified either way.
- **Net Recovery Value is computed from *expected*, not *realized*, recovered revenue** for
  every baseline — a baseline with poorly-calibrated probabilities (ML_ONLY, ECE ≈0.26 on the
  last run) can show a Net Recovery Value far higher than its actual recovered revenue. This
  is disclosed explicitly in `docs/ml-evaluation.md`, not smoothed over.

## Razorpay integration

- **Live Razorpay Test Mode calls require `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` to be
  configured.** Every adapter (`payment_link_adapter.py`, `subscription_adapter.py`) is
  implemented against the verified real API shape (`docs/razorpay-integration.md`) and calls
  the live API directly once credentials are set; without them, a clearly-labeled simulator
  implementing the same interface takes over so the rest of the pipeline behaves identically.
- **Plain `payment.captured` events with no `payment_link` entity carry no recovery
  correlation information at all.** If a merchant's webhook configuration doesn't include
  `payment_link.paid`, a payment made through a recovery Payment Link cannot be traced back to
  its originating case — the payment itself is still reconstructed correctly, but
  `outcome_service.reconcile_outcome()` has nothing to match it against. This is a real gap in
  that specific (avoidable, by subscribing to the right webhook events) configuration, not a
  silently swallowed failure — see `docs/razorpay-integration.md` §10.
- **Partial payments are prevented at creation, not specially handled at reconciliation.**
  Every recovery Payment Link is created with `accept_partial: false`
  (`payment_link_adapter.py`), so Razorpay itself refuses to let a customer settle less than
  the full amount through a RecoveryOS-created link. `reconcile_outcome()` still doesn't
  independently branch on `amount < case.amount` for the theoretical case of a captured amount
  not matching the case amount via some other path — defense-in-depth at the reconciliation
  layer remains a reasonable future hardening step.

## Subscriptions

- **Subscription recovery is a real but partial extension, not a fully supported workflow.**
  The real merchant-side levers (`subscription_card_change`, invoice charging) are implemented
  and tested; `revenue_signal_service.py`/`razorpay_payload_parser.py` do not parse
  `subscription.*` webhook events, so subscription opportunities aren't auto-created by the
  autonomous pipeline. The primary, fully supported workflow is one-time payment failure →
  recovery.

## Infrastructure and reproducibility

- **Docker Compose** (`docker-compose.yml`/`backend/Dockerfile`) is the standard way to run
  the full local stack (Postgres + backend + frontend) in one command — see
  `docs/deployment.md`. The native-Postgres path (Quickstart in `README.md`) is the
  alternative for a development environment without Docker.
- **Render deployment** — `render.yaml` and the Dockerfiles are written for a one-click Render
  deploy; see `docs/deployment.md` for the steps.

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
