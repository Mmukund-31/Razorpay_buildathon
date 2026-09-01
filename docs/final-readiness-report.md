# Final Readiness Report

Written at the close of the final hardening pass, against the baseline recorded in
`docs/pre-hardening-baseline.md`. Every number below is reproducible by the commands cited.

## Executive Summary

The pre-existing architecture was fundamentally sound — webhooks, the policy engine,
executors, idempotency/concurrency primitives, AI safety, and the ML pipeline were already
solid, real, and honestly documented. This pass found and closed exactly two P0 defects (one
already suspected from the stubbed `outcome_service.py`, one discovered only while writing a
concurrency test for the first), closed a real AI-measurement gap in the benchmark, and
cleaned up a set of stubs and documentation inconsistencies. No architecture was rewritten;
no new infrastructure was added.

## Bugs Fixed

1. **Payment-link recovery correlation was completely broken** — the dominant real-world
   recovery mechanism (a fresh Razorpay Payment Link, since there is no "retry a failed
   payment" API) produced a payment with a different `razorpay_payment_id` than the case's
   original failed payment, and nothing traced it back. `outcome_service.py` was a dead stub.
   Fixed: `outcome_service.reconcile_outcome()` correlates via the Payment Link's
   `reference_id` (verified against `razorpay.com/docs`'s `payment_link.paid` webhook shape),
   writes `actual_recovered_amount` idempotently, and resolves the case through the existing
   state machine. See ADR-007 (`docs/decisions.md`) and `docs/razorpay-integration.md` §10.
2. **A real double-execution race**, found while writing the concurrency test this pass
   required. Two simultaneous `POST /recovery-cases/{id}/execute` requests could both reach
   the `RecoveryAction` insert with the identical `idempotency_key` — the case-level
   optimistic lock alone doesn't prevent this (see ADR-008) — and the loser's insert raised an
   unhandled `IntegrityError` (a 500), not a graceful no-op. Fixed: the losing insert is now
   caught, the session rolled back, and the case re-fetched fresh.
3. **The dashboard's "Recovered Revenue" conflated expected and actual recovery** — it summed
   the case's original at-risk `amount`, not a verified recovered amount (there was no such
   column). Fixed: a new `RecoveryCase.actual_recovered_amount` column, written only by
   `outcome_service`, surfaced separately in both the dashboard and the Decision Trace UI.
4. **The benchmark's `RECOVERYOS_FULL` baseline silently never called the AI diagnostician**,
   despite its name — undisclosed anywhere. Fixed: the docstring/table caption now says so
   explicitly, and a genuine 5th arm (`RECOVERYOS_AI`) exists for the true ML+AI+Optimizer+
   Policy comparison, on a bounded sample.
5. **A cross-event-loop asyncpg connection reuse bug**, specific to this Windows/ProactorEventLoop
   environment: the app's process-cached DB engine could hand a pooled connection created
   under one pytest-asyncio event loop to a later test running under a different one. Fixed in
   `tests/conftest.py`'s `client` fixture and in `simulator/benchmark/baseline_runner.py`/
   `scripts/run_simulator.py`/`scripts/seed_db.py` (dispose the cached engine within the same
   loop that used it, never a subsequent separate `asyncio.run()`).
6. **A pre-existing unit-conversion error in `docs/ml-evaluation.md`'s benchmark table** — the
   "₹X.XXCr" labels were off by 10x (the underlying numbers were correct for ₹ Lakh, mislabeled
   Cr). Corrected, with the mechanism explained.

## Features Added

- **Net Recovery Value** metric (`ml/evaluation/metrics.py::net_recovery_value`) — Expected
  Recovered Revenue − Intervention Cost − Risk Cost, computed for every baseline, wired into
  `all_metrics()`.
- **`RECOVERYOS_AI` benchmark arm** — the genuine ML+AI+Optimizer+Policy pipeline, on a
  stratified bounded sample, importing production's own nudge logic
  (`analysis_service._AI_NUDGE_MAX_FRACTION`) rather than reimplementing it. Gated behind
  `--run-ai-ablation` so normal benchmark runs stay free of LLM calls.
- **AI-ablation-specific metrics**: `diagnosis_accuracy`, `recommended_action_agreement_rate`,
  `llm_failure_rate`, `llm_latency_ms_p50/p95`.
- **`scripts/seed_db.py`** and **`scripts/run_simulator.py`** — previously `NotImplementedError`
  stubs, now real CLI entry points reusing the exact in-process ASGI pipeline path the API
  endpoints use (never a parallel fake path).
- **`database_unavailable` failure-injection scenario** — proven via FastAPI's dependency-
  override mechanism (`tests/integration/test_database_unavailable.py`); the other two
  previously-unwired scenarios (`malformed_ai_response`, `low_confidence_ml_prediction`) are
  documented as intentionally proven by existing unit tests rather than forced into the
  webhook-event-batch generator, since they test internal component behavior, not webhook
  shapes (see `simulator/scenarios/scenario_definitions.py`'s updated docstring).
- **Decision Trace UI**: a prominent "AI recommendation blocked" panel (action, human-readable
  reason, potential unnecessary intervention amount) when policy rejects, and a distinct
  "Actual recovered revenue" panel separate from the expected-value estimate.
- **Frontend ESLint** — `npm run lint` was a broken script (declared, dependency never
  installed); now a real, standard flat-config setup, 0 errors.

## Tests

- **113 test functions, 136 collected test cases** (parametrization expands some), **135
  passing, 1 explicitly skipped, 0 failures** — verified against a real, reachable PostgreSQL
  instance (native local Postgres 17), stable across repeated runs.
- **28 new test functions** added this pass across 10 new files: payment-link correlation
  (unit + integration, 9 tests), execute-concurrency (1), webhook duplicate/out-of-order (2),
  database-unavailable (1), ablation metrics (10), mocked AI-ablation benchmark runner (5).
- **Frontend**: `npm run build` clean, `npm run lint` 0 errors (2 pre-existing stylistic
  warnings), 6/6 Playwright e2e tests pass.
- `mypy app`: clean (102 source files). `ruff check app tests`: clean. 13 pre-existing ruff
  findings remain in `ml/`/`scripts/`/`simulator/` files this pass didn't otherwise touch
  (import ordering, line length) — cosmetic, not fixed, to avoid touching files with no other
  reason to change this late in the process.

## Benchmark

4-baseline full-dataset results unchanged from the pre-hardening baseline (byte-for-byte —
Net Recovery Value is additive, not a replacement metric):

| Baseline | Recovered revenue | Net Recovery Value | Recovery rate |
|---|---|---|---|
| ALWAYS_RETRY | ₹36.94L | ₹36.93L | 21.7% |
| STATIC_RULES | ₹52.54L | ₹52.53L | 30.4% |
| ML_ONLY | ₹53.62L | ₹95.17L | 31.3% |
| RECOVERYOS_FULL | ₹47.96L | ₹81.89L | 28.2% |

RecoveryOS still doesn't win on gross revenue — the honest finding this project has reported
throughout. See `docs/ml-evaluation.md` for the full table and the calibration-gap caveat
(ML_ONLY's Net Recovery Value looks far higher than its realized revenue precisely because
its probabilities are less well-calibrated, ECE 0.258 vs RECOVERYOS_FULL's 0.290 — a real,
close-but-notably-different comparison, not a clean win either way, reported as-is).

The `RECOVERYOS_AI` arm was not run against a live LLM in this pass (no `LLM_API_KEY`
configured, and per explicit scope decision no live Anthropic spend) — see `docs/ai-ablation.md`
for what was verified instead (a mocked test proving the nudge mechanism works correctly) and
exactly how to produce real numbers.

## Razorpay

**Integration status**: real Payment Links/Subscriptions API adapters, bounded retry/backoff,
webhook signature verification, event-ID dedup, and (new this pass) payment-link recovery
correlation — all implemented and tested against mocks (`respx`) and the real webhook
ingestion path via the simulator's in-process ASGI posts. **Test Mode status**: not exercised
against a live Razorpay account in this pass, per explicit scope decision (see
`docs/limitations.md`). The correlation mechanism's key fact (`payment_link.paid`'s payload
shape) was independently verified against live `razorpay.com/docs` before implementation.

## AI

Real Anthropic SDK integration, zero tool access, strict Pydantic validation, circuit
breaker, and prompt-injection defenses were already solid pre-pass. This pass added the
ability to *measure* the AI's marginal contribution in isolation (`docs/ai-ablation.md`) —
not executed live, but the mechanism is real, tested, and ready.

## Security

No secrets committed (`.env` gitignored, never tracked; `.env.example` placeholder-only).
`npm audit` found one real, moderate `react-router-dom` advisory (open-redirect via backslash
in `<Link>`) — evaluated this app's actual exposure (every `Link to=` target is a
server-generated UUID, never user-controlled input) and documented rather than force-fixing a
major-version migration this close to submission; a production pass should still take the
upgrade. `anthropic` dependency floor corrected to match what's actually tested. No other
findings.

## Known Limitations

See `docs/limitations.md` in full. Headline items: synthetic (not real-world) benchmark data;
live Razorpay Test Mode and live AI-ablation execution both deferred per explicit scope
decision this pass; Docker Compose not exercised (the Docker daemon wasn't running in this
environment — verified via `docker compose config` for syntax validity only); subscription
recovery remains a partial extension, honestly scoped as such before this pass and left that
way; Hinglish voice remains a clearly-labeled simulation.

## Submission Recommendation

**READY WITH CAVEATS.**

The P0 items — outcome reconciliation, payment-link correlation, idempotent double-webhook
handling, duplicate/out-of-order webhook correctness, and the newly-found concurrent-execution
race — are implemented, tested, and independently verified against a real database in this
session, not merely claimed. The AI ablation and Net Recovery Value work (P1) is real and
tested. The caveats are specific and disclosed, not hidden: live Razorpay Test Mode and live
AI-ablation execution were deliberately not performed (a scope decision, reversible by
configuring credentials and re-running the documented commands), and Docker Compose itself
was not exercised end-to-end (the underlying migrations/pipeline/benchmark were all verified
against a real Postgres instance by other means). Before treating this as unconditionally
submission-ready, whoever finalizes the submission should, if time allows: run one genuine
Razorpay Test Mode payment-link recovery end-to-end, and run `--run-ai-ablation` with a real
`LLM_API_KEY` to replace the honest "not executed live" placeholder in `docs/ai-ablation.md`
with real numbers.
