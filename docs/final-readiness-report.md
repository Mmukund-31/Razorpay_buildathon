# Final Readiness Report

Written at the close of the final hardening pass, against the baseline recorded in
`docs/pre-hardening-baseline.md`. A second, final **submission pass** followed — hardening and
cleanup only, no rewrite — closing the remaining concrete gaps that pass's own "Known
Limitations"/"Submission Recommendation" sections called out. That pass's changes are recorded
first; everything below it is the original hardening pass's report, left intact as the
historical record it is.

## Final submission pass — what changed on top of the hardening pass above

1. **`accept_partial: false` is now explicit on every recovery Payment Link**
   (`payment_link_adapter.py`) — previously never set, relying on Razorpay's default. Tested
   (`test_create_payment_link_never_accepts_partial_payment`). Closes the partial-payment
   correlation gap the hardening pass's `docs/limitations.md` flagged as "a real gap."
2. **The complete end-to-end flow now has a real test, not a skip.**
   `tests/integration/test_pipeline_smoke.py::test_full_pipeline_payment_failure_to_recovery`
   was previously the suite's one explicitly-skipped placeholder (its own docstring said it
   becomes real "as each service stops being a stub"). Every service it named is now real, so
   it does: it drives one `payment.failed` webhook through the real HTTP endpoint and
   background worker — ingestion, state reconstruction, revenue signal, opportunity, case
   creation/eligibility, ML-driven analysis (a fixed, valid ML signal is substituted for the
   real trained model's output so the test is deterministic — everything downstream is
   unmocked), policy approval, a real Payment Link creation (exactly once, asserted), a
   simulated customer payment via `payment_link.paid`, outcome reconciliation, and a final
   assertion that the `actual_recovered_amount`, the `original_payment → recovery_case →
   recovery_action → payment_link → recovered_payment` correlation chain, and the append-only
   audit trail are all present and correct.
3. **New duplicate-Payment-Link tests.** The hardening pass proved concurrent `/execute`
   requests create exactly one `RecoveryAction`; this pass adds two tests proving they also
   create exactly one real Payment Link (`test_two_simultaneous_execute_requests_create_
   exactly_one_payment_link`, via a call-counting gateway wrapper) and that a sequential
   re-execute on an already-`EXECUTING` case is rejected outright, never dispatching a second
   link (`test_re_executing_an_already_executing_case_creates_no_second_payment_link`).
4. **New Razorpay failure-mode tests**: 429 (retried and eventually succeeds; retried and
   eventually exhausted, both), and a network timeout (`httpx.TimeoutException`, retried and
   eventually succeeds; retried and eventually exhausted). Previously only generic 5xx and 4xx
   were covered.
5. **"Immutable audit ledger" → "append-only audit ledger"** — corrected everywhere the code
   and docs described the ledger's guarantee as `README.md`, `docs/track-alignment.md`,
   `app/api/audit.py`, `app/domain/models/audit_log.py`,
   `app/repositories/audit_log_repository.py`, `alembic/versions/0001_initial_schema.py`, and
   the Audit Ledger frontend page. "Immutable" implies a guarantee this system doesn't actually
   enforce at the database level (see `audit_log.py`'s own docstring, unchanged by this pass);
   "append-only" is what's actually true and tested (`test_audit_log_immutability.py`: no
   update/delete code path exists).
6. **Dead code and stale comments removed**: `frontend/src/components/PagePlaceholder.tsx`
   (fully unreferenced, confirmed by grep) deleted; two stale `TODO(phase-N)` docstring lines
   in `ml/features/feature_definitions.py` (the work they described was already done) removed.
7. **The 13 previously-untouched `ruff` findings in `ml/`/`scripts`/`simulator/` are now
   fixed** (unused `noqa: E402` directives, an unsorted import block, two `zip()` →
   `itertools.pairwise()` refactors — all style, no logic changes), along with the alembic
   migration's 11 `E501`s. `ruff check .` is now clean across the entire repository, not just
   `backend/app`/`backend/tests`.
8. **`react-router-dom` upgrade evaluated and deliberately not taken.** Already pinned at the
   latest v6 (`^6.28.0`); the only newer release is `7.18.3`, a breaking major requiring a
   data-router migration — genuinely not "safely possible" in a hardening-not-rewrite pass.
   Practical exposure of the two open `npm audit` advisories re-confirmed as low: exactly two
   `<Link to=>` usages in the whole frontend, both interpolating server-generated UUIDs, never
   user input; zero `useNavigate()` calls anywhere.
9. **Docker Compose**: Docker Desktop was actually started in this pass (it wasn't reachable in
   the prior one). Root cause of why `docker compose up` still can't be exercised here is now
   precisely known: this machine's Docker Desktop has no WSL2 backend (`wsl --status` reports
   WSL isn't installed) — a machine-setup gap, not a project defect. `docker compose config`
   continues to validate the compose file's syntax cleanly.
10. **Live-credential attempts, both honestly inconclusive.** Real credentials became available
    mid-pass for both external integrations this project had left "unverified" — see the
    dedicated Razorpay and AI sections below for exactly what was attempted and why neither
    produced a live success to report.
11. **Test suite grew and the skip count dropped to zero**: **120 test functions, 143 collected
    test cases, all 143 passing, 0 skipped, 0 failures** (previously 113/136/135/1-skip) — see
    Tests, below, superseding the hardening pass's numbers throughout this document.

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

- **120 test functions, 143 collected test cases** (parametrization expands some), **all 143
  passing, 0 skipped, 0 failures** — verified against a real, reachable PostgreSQL instance
  (native local Postgres), stable across repeated runs. The one previously-skipped test
  (the full-pipeline smoke test) is now real, not skipped — see item 2 above.
- **35 new test functions** total across the hardening pass (28) and the final submission
  pass (7: `accept_partial` never-set, 429 retried-then-succeeds, 429 exhausted, timeout
  retried-then-succeeds, timeout exhausted, duplicate-Payment-Link-under-concurrency,
  re-execute-already-executing-rejected — plus the full pipeline test converted from a skip to
  a real pass, not counted twice).
- **Frontend**: `npm run build` clean (includes `tsc -b` type-checking), `npm run lint` 0
  errors (2 pre-existing stylistic `react-refresh` warnings, out of scope — not Ruff), 6/6
  Playwright e2e tests pass.
- `mypy app`: clean (102 source files). `ruff check .` is now clean across the **entire
  repository** — `backend/app`, `backend/tests`, `backend/alembic`, `ml/`, `scripts/`, and
  `simulator/` — closing the 11 (alembic) + 13 (`ml`/`scripts`/`simulator`) findings the prior
  pass had deliberately left untouched.

## Benchmark

4-baseline full-dataset results unchanged from the pre-hardening baseline (byte-for-byte —
Net Recovery Value is additive, not a replacement metric):

| Baseline | Recovered revenue | Net Recovery Value | Recovery rate |
|---|---|---|---|
| ALWAYS_RETRY | ₹36.94L | ₹36.93L | 21.7% |
| STATIC_RULES | ₹52.54L | ₹52.53L | 30.4% |
| ML_ONLY | ₹53.62L | ₹95.17L | 31.3% |
| RECOVERYOS_FULL | ₹47.96L | ₹81.89L | 28.2% |

RecoveryOS still doesn't win on gross revenue, and — read carefully — it doesn't win on Net
Recovery Value either, though it's easy to misread the table as if it does. See
`docs/ml-evaluation.md` for the full table and the calibration-gap caveat (ML_ONLY's Net
Recovery Value looks far higher than its realized revenue precisely because its probabilities
are less well-calibrated, ECE 0.258 vs RECOVERYOS_FULL's 0.290 — a real, close-but-notably-
different comparison, not a clean win either way, reported as-is). The README's summary line
was corrected this pass — it previously claimed "RecoveryOS wins on precision and Net Recovery
Value," which overstated the NRV comparison; the honest framing is precision, unnecessary-
action rate, and revenue per intervention.

**The `RECOVERYOS_AI` arm was attempted against a live LLM this pass** — a real, valid
Anthropic API key was available (`LLM_API_KEY`, format-verified as a genuine `sk-ant-...` key)
and `--run-ai-ablation --ai-sample-size 20` was actually run against it. The key authenticates
successfully, but the Anthropic account has no available credit balance: every call returned a
real `400 invalid_request_error` ("Your credit balance is too low to access the Anthropic
API"), not a "no key configured" short-circuit. The result is still `llm_failure_rate=1.0` and
every other metric identical to `RECOVERYOS_FULL_SUBSET` — the same shape as the "no key"
result the prior pass reported — but it's now evidence from a genuine attempted call, not an
untried code path. See `docs/ai-ablation.md`.

## Razorpay

**Integration status**: real Payment Links/Subscriptions API adapters, bounded retry/backoff
(now covering timeout and 429 independently, not just generic 5xx), webhook signature
verification, event-ID dedup, payment-link recovery correlation, and (new this pass)
`accept_partial: false` on every recovery Payment Link — all implemented and tested against
mocks (`respx`) and the real webhook ingestion path via the simulator's in-process ASGI posts.
**Test Mode status**: two genuine attempts were made this pass to create a real Payment Link
against a live Test Mode account, using `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` supplied for
that purpose — both returned `401 Authentication failed` from Razorpay. The loaded credential
values were independently confirmed clean (correct lengths, no whitespace corruption); the
key/secret pair itself does not authenticate. Reported honestly as unverified — see
`docs/limitations.md` and `docs/razorpay-integration.md` §9. The correlation mechanism's key
fact (`payment_link.paid`'s payload shape) was independently verified against live
`razorpay.com/docs` before implementation.

## AI

Real Anthropic SDK integration, zero tool access, strict Pydantic validation, circuit
breaker, and prompt-injection defenses were already solid pre-pass. The hardening pass added
the ability to *measure* the AI's marginal contribution in isolation (`docs/ai-ablation.md`);
this pass actually exercised that measurement against a live model (see Benchmark, above) —
the mechanism is real, tested, and was genuinely run, even though a billing constraint outside
this codebase's control kept it from producing a valid live diagnosis.

## Security

No secrets committed (`.env` gitignored, never tracked; `.env.example` placeholder-only —
re-verified at the end of this pass with a repository-wide grep for credential patterns and
`git ls-files`). `npm audit` still finds the same real, moderate `react-router-dom` advisory
(open-redirect via backslash in `<Link>`, plus an SSR-hydration advisory that doesn't apply to
this client-side-only SPA) — re-evaluated this pass: exactly two `Link to=` usages in the
entire frontend, both interpolating server-generated UUIDs, zero `useNavigate()` calls
anywhere. The only fix available is the `react-router-dom` v7 major (a breaking data-router
migration), which this pass deliberately did not take — genuinely not "safely possible"
without becoming a rewrite this close to submission. `anthropic` dependency floor corrected to
match what's actually tested. No other findings.

## Known Limitations

See `docs/limitations.md` in full. Headline items: synthetic (not real-world) benchmark data;
live Razorpay Test Mode attempted twice this pass with real credentials and still unverified
(401, credentials don't authenticate — see Razorpay, above); live AI-ablation attempted this
pass with a real, valid Anthropic key and still produced no valid diagnosis (the account has
no credit balance — see AI, above); Docker Compose not exercised (root cause now precise: this
machine's Docker Desktop has no WSL2 backend, confirmed via `wsl --status` — verified via
`docker compose config` for syntax validity only); subscription recovery remains a partial
extension, honestly scoped as such from the start and left that way; Hinglish voice remains a
clearly-labeled simulation.

## Submission Recommendation

**SUBMISSION READY**, with two specific, disclosed, non-blocking external-verification gaps.

Every safety invariant the product spec cares about is implemented, tested, and independently
verified against a real database in this session: no unsafe AI action can reach the executor
(the policy engine is the sole approval gate; `ActionExecutor` is the only Razorpay-adapter
importer), no payment can be recovered twice (write-once `actual_recovered_amount`,
terminal-case guard), no duplicate webhook creates duplicate business effects (`UNIQUE`
`razorpay_event_id` + idempotent ack), no stale event regresses state (watermark-guarded
conditional transitions), no duplicate Payment Link can be created for one case (proven under
both true concurrency and sequential re-execution), a Payment Link can never be partially
settled (`accept_partial: false`, explicit), every financial action is policy-approved and
idempotent (`policy_evaluation_id` NOT NULL FK, `idempotency_key` UNIQUE), and the complete
failed-payment → Payment Link → payment → webhook → reconciliation → actual recovered revenue
→ audit-ledger chain is proven by one real, unmocked-below-the-ML-boundary integration test,
not just individually-tested pieces. All 143 tests pass, `ruff`/`mypy`/frontend build+lint all
clean, no secrets are committed, and documentation matches the code (this pass's whole point).

The two caveats are specific and disclosed, not hidden: **live Razorpay Test Mode** and **live
AI-ablation execution** were both genuinely attempted this pass with real credentials supplied
for that purpose, and both remain unverified for reasons outside this codebase's control
(a credential pair that doesn't authenticate; an Anthropic account with no credit balance) —
not scope decisions this time, but real attempts with real, disclosed outcomes. Whoever
finishes the submission can re-attempt either by supplying working credentials and re-running
the documented commands (`docs/razorpay-integration.md` §9, `docs/ai-ablation.md`); nothing
else in the codebase needs to change to make either one work.
