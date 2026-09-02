# Readiness Summary

A concise statement of what's built, what's verified, and how to check it yourself. For the
detailed requirement-by-requirement mapping, see `docs/track-alignment.md`; for the precise
scope boundary (synthetic vs. real, simulated vs. live), see `docs/limitations.md`.

## What's real

Every stage of the pipeline is real, production code — not a stub, not a mock standing in for
unfinished work:

- **Webhook ingestion**: real HMAC-SHA256 signature verification, idempotent persistence
  (`UNIQUE` constraint on the Razorpay event id), background-worker processing.
- **State reconstruction**: a pure, unit-tested state machine that resolves payment status
  from webhook events with strict ordering guarantees — a stale or out-of-order event can
  never regress state.
- **ML scoring**: a real trained LightGBM model (`ml/inference/predictor.py`), evaluated
  against a real held-out test set (`docs/ml-evaluation.md`).
- **AI diagnosis**: a real Anthropic integration with zero tool access, strict Pydantic
  validation of its output, and a circuit breaker — the pipeline degrades gracefully to
  ML-only scoring if the AI is unavailable or its output is invalid, never blocking or
  crashing.
- **Optimizer**: pure expected-value arithmetic combining the ML signal (and a bounded AI
  nudge) into a ranked list of candidate actions.
- **Policy engine**: 8 deterministic rules — the only thing that can approve a financial
  action. The AI's opinion never bypasses it.
- **Executor**: real Razorpay Payment Link / Subscription adapters, with bounded retry on
  transient failures (timeout, 429, 5xx) and every recovery Payment Link created with
  `accept_partial: false`. Falls back to a clearly-labeled simulator when no Razorpay
  credentials are configured, so the pipeline behaves identically either way.
- **Outcome reconciliation**: correlates a new payment made through a recovery Payment Link
  back to its originating case via the link's `reference_id`, writes the actual recovered
  amount exactly once (idempotently), and resolves the case through the same state machine
  every other transition uses.
- **Audit ledger**: every hop of the pipeline appends one row; the ledger is append-only by
  construction (no update/delete code path exists).

## Safety guarantees

- A payment cannot be recovered twice — a payment link can never be created twice for the
  same case, and never accepts a partial payment.
- A duplicate or out-of-order webhook can never create a duplicate business effect or regress
  state.
- No financial action executes without a policy-approved, idempotent `recovery_action` row.
- The AI can influence which action is *ranked* highest, within a bounded nudge; it can never
  itself approve or execute an action.

The complete flow — a failed payment, through detection, ML/AI analysis, policy approval,
Payment Link creation, the customer's payment, webhook delivery, outcome reconciliation, and
the actual recovered amount landing in the audit ledger — is proven end to end by
`backend/tests/integration/test_pipeline_smoke.py`, not just tested piece by piece.

## Tests

**120 test functions, 143 collected test cases, all passing.**

```bash
cd backend
pip install -e ".[dev]"
pytest              # full suite, against a real Postgres instance
pytest -m "unit or smoke"   # no external dependencies needed
ruff check .
mypy app
```

`ruff check` is clean across the entire repository (`backend/`, `ml/`, `scripts/`,
`simulator/`); `mypy app` is clean. Frontend: `npm run build` and `npm run lint` are clean,
and the Playwright smoke suite (`npm run test:e2e`) passes.

## Benchmark

A 4-baseline benchmark (Rules, ML, ML+Policy, and full RecoveryOS) runs against 7,500
held-out synthetic rows with a fixed seed:

```bash
python simulator/benchmark/baseline_runner.py
```

RecoveryOS trades a small amount of raw recovered revenue for discipline — the highest
precision, the lowest unnecessary-action rate, the highest revenue per intervention, and a
real, measured policy-rejection rate. Full table and discussion in `docs/ml-evaluation.md`;
the AI-inclusive 5th benchmark arm is in `docs/ai-ablation.md`.

## Scope

RecoveryOS's first-class, fully-wired workflow is failed one-time payment → recovery,
including the Hinglish voice channel. Subscription recovery has real, tested Razorpay levers
but isn't yet auto-triggered by the autonomous pipeline. See `docs/track-alignment.md` for the
complete requirement mapping and `docs/limitations.md` for what's synthetic, simulated, or
deliberately out of scope.
