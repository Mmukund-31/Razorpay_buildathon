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
- **The AI-ablation arm (`RECOVERYOS_AI`) was attempted against a live LLM in the final
  submission pass and still didn't produce a valid diagnosis** — a real, format-valid
  `LLM_API_KEY` was available and `--run-ai-ablation --ai-sample-size 20` was actually run
  against it (not a mocked test this time). The key authenticates, but the Anthropic account
  has no available credit balance, so every call returned a genuine `400
  invalid_request_error` from Anthropic ("Your credit balance is too low"), not a "no key"
  short-circuit. `llm_failure_rate` is still `1.0`. The code path is real, exercised against
  the live API this time (not just unit-tested with a mock), and ready to produce real numbers
  the moment the account has credit; see `docs/ai-ablation.md`.
- **Net Recovery Value is computed from *expected*, not *realized*, recovered revenue** for
  every baseline — a baseline with poorly-calibrated probabilities (ML_ONLY, ECE ≈0.26 on the
  last run) can show a Net Recovery Value far higher than its actual recovered revenue. This
  is disclosed explicitly in `docs/ml-evaluation.md`, not smoothed over.

## Razorpay integration

- **Live Razorpay Test Mode execution was attempted, twice, in the final submission pass, and
  remains unverified.** `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` were supplied specifically for
  this purpose, and `PaymentLinkAdapter.create_payment_link()` — the real production code
  path — was actually called against Razorpay's live API. Both attempts returned `401
  Authentication failed`; the loaded credential values were independently confirmed clean (no
  whitespace corruption, correct lengths and prefix), so the key/secret pair itself does not
  authenticate. Every adapter (`payment_link_adapter.py`, `subscription_adapter.py`) is
  implemented against the verified real API shape (`docs/razorpay-integration.md`) and is
  exercised in tests via `respx`-mocked HTTP, never a hand-waved stub — but a genuine
  end-to-end Test Mode payment (create a real test-mode Payment Link, pay it via Razorpay's
  mock bank page, receive the real webhook) has still not been completed against a live
  account. Re-attempting needs only a working key pair from the Razorpay dashboard.
- **Plain `payment.captured` events with no `payment_link` entity carry no recovery
  correlation information at all.** If a merchant's webhook configuration doesn't include
  `payment_link.paid`, a payment made through a recovery Payment Link cannot be traced back to
  its originating case — the payment itself is still reconstructed correctly, but
  `outcome_service.reconcile_outcome()` has nothing to match it against. This is a real gap in
  that specific (avoidable, by subscribing to the right webhook events) configuration, not a
  silently swallowed failure — see `docs/razorpay-integration.md` §10.
- **Partial payments are prevented at creation, not specially handled at reconciliation.**
  Since the final submission pass, every recovery Payment Link is created with
  `accept_partial: false` (`payment_link_adapter.py`), so Razorpay itself refuses to let a
  customer settle less than the full amount through a RecoveryOS-created link — the practical
  gap this bullet used to describe. `reconcile_outcome()` still doesn't independently branch on
  `amount < case.amount` for the (now-excluded-at-source, but theoretically still possible via
  some other path) case of a captured amount not matching the case amount — defense-in-depth
  at the reconciliation layer remains a reasonable future hardening step, not a currently
  exploitable gap given `accept_partial: false`.

## Subscriptions

- **Subscription recovery is a real but partial extension, not a fully supported workflow**
  (already honestly scoped in `docs/track-alignment.md` before this hardening pass, and left
  that way). The real merchant-side levers (`subscription_card_change`,
  invoice charging) are implemented and tested; `revenue_signal_service.py`/
  `razorpay_payload_parser.py` do not parse `subscription.*` webhook events, so subscription
  opportunities aren't auto-created by the autonomous pipeline. The primary, fully supported
  workflow is one-time payment failure → recovery.

## Infrastructure and reproducibility

- **Docker Compose was not exercised end-to-end.** Docker Desktop was actually started during
  the final submission pass (it wasn't reachable during the prior hardening pass), and the
  root cause is now precisely known rather than just "the daemon wasn't running": this
  machine's Docker Desktop has no WSL2 backend installed (`wsl --status` reports WSL itself
  isn't installed), so the Docker engine cannot start here at all — a machine-setup gap, not a
  project defect. `alembic upgrade head`, the full test suite, the ML training pipeline, and
  the benchmark were all verified against a real, reachable PostgreSQL instance (a native
  Windows Postgres service, not Docker) instead. Docker Compose's configuration (healthchecks,
  startup ordering, migration-at-container-start) continues to validate cleanly via `docker
  compose config` but has not been run. Installing WSL2 would resolve this but requires a
  system-level change and reboot outside this pass's scope.
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
