# Pre-Hardening Baseline

Captured before any code changes in the final-readiness hardening pass (2026-09-01). This is
the "before" snapshot the final report (`docs/final-readiness-report.md`) diffs against.

## Environment

- Python 3.14.4, backend virtualenv at `backend/.venv`
- Node v24.15.0
- Docker: Docker CLI 29.7.2 / Compose v5.4.0 installed, but the Docker Desktop daemon was
  **not running** in this session (`docker ps` failed to reach the daemon) — `docker compose
  up` was not exercised live in this pass; see `docs/limitations.md`.
- PostgreSQL: a native Windows PostgreSQL 17 service (`postgresql-x64-17`) was already running
  and reachable at the configured `DATABASE_URL`, listening on `5432` — **not** the Docker
  Compose Postgres service. Migration `0001` was already applied and matches `alembic heads`.

## Backend tests

```
cd backend && .venv/Scripts/python.exe -m pytest -v
```

**89 passed, 1 skipped, 90 collected, 4.37s.** The single skip is
`test_pipeline_smoke.py::test_full_pipeline_payment_failure_to_recovery`, marked
`@pytest.mark.skip` explicitly (not a DB-connectivity self-skip) — because it exercises the
full autonomous pipeline end-to-end and predates `outcome_service` being wired up correctly
for the payment-link correlation case this pass fixes.

Because a real Postgres was reachable, **all DB-gated tests ran for real** rather than
self-skipping: `test_db_connectivity.py` (2), `test_webhook_ingestion.py` (2),
`test_idempotency.py` (1) all passed against the live database, not just against mocks.

**Test count reconciliation**: `grep -rn "def test_" tests --include="*.py" | wc -l` = **79**
distinct test functions, expanding to **90** collected pytest items due to parametrization
(`test_config.py` ×3 params, `test_optimizer.py` ×3 params,
`test_recovery_case_state_machine.py` ×8 params on one test). Prior documentation stated 77,
83, and 89 in different places — none matched each other or this measurement. This baseline
is the number of record until the hardening pass's new tests are added, at which point
`docs/README.md` etc. will be updated to the final verified count.

## Frontend

- `npm run build` (`tsc -b && vite build`): **clean**, no type errors, build succeeds
  (190.95 kB JS, 12.53 kB CSS, gzip 60.69 kB / 3.02 kB).
- `npm run test:e2e` (Playwright, 6 smoke tests across all 5 routes + nav): **6/6 passed**.
- `npm run lint`: **fails to run** — `package.json` declares `"lint": "eslint ."` but
  `eslint` is not listed in `devDependencies` and is not installed. Pre-existing gap, not
  introduced by this pass; flagged for a P2 fix (either add a minimal eslint config +
  dependency, or remove the dead script).

## Static analysis (backend)

- `mypy app`: **clean** — "Success: no issues found in 101 source files."
- `ruff check .`: **11 findings, all confined to `alembic/env.py` and
  `alembic/versions/0001_initial_schema.py`** (import ordering, `typing.Sequence` vs
  `collections.abc.Sequence`, `Union[X, None]` vs `X | None`, a few lines >110 chars in
  auto-generated-style column definitions). Zero findings in `app/`. Pre-existing, low-risk,
  fixable with `--fix` for most; addressed opportunistically in the P2 cleanup pass.

## ML / Benchmark — captured exactly as currently implemented, before any change

```
backend/.venv/Scripts/python.exe simulator/benchmark/baseline_runner.py
```

| Baseline | Recovered revenue (paise) | Recovery rate | Revenue/intervention | Policy rejection |
|---|---|---|---|---|
| ALWAYS_RETRY | 369,419,242 | 21.65% | 49,256 | 0% |
| STATIC_RULES | 525,395,128 | 30.40% | 71,844 | 0% |
| ML_ONLY | 536,218,639 | 31.33% | 71,496 | 0% |
| RECOVERYOS_FULL | 479,584,035 | 28.16% | 76,064 | 15.93% |

Matches `docs/ml-evaluation.md`'s published table exactly (`simulator/benchmark/results/latest.json`
byte-for-byte) — confirming these numbers are genuinely reproducible from the runner, not
hand-authored. `_persisted_to_db: true` — the live Postgres above accepted the
`experiments`/`experiment_results` writes.

**Confirmed via direct code reading**: `RECOVERYOS_FULL` does not call
`app.agents.ai_diagnostician` anywhere — it is ML + Optimizer + Policy only. This is the
subject of one of the two P0 fixes below.

## Known TODOs / stubs at baseline (full repo grep for
`TODO|FIXME|NotImplementedError|stub|placeholder|hardcod|mock|fake`)

Genuine, unimplemented:
- `backend/app/services/outcome_service.py` — dead stub (`NotImplementedError`), never
  imported anywhere. **P0.**
- `scripts/seed_db.py` — `NotImplementedError` stub.
- `scripts/run_simulator.py` — `NotImplementedError` stub, referenced by name in
  `frontend/src/pages/Benchmark.tsx`'s empty-state UI text (non-functional if a user follows
  that instruction).
- `simulator/scenarios/scenario_runner.py` — implements 5 of 8 documented scenarios;
  `malformed_ai_response`, `low_confidence_ml_prediction`, `database_unavailable` have no
  runner.

Stale comments only (already-completed work, no functional gap): two leftover
`TODO(phase-N)` docstring lines in `ml/features/feature_definitions.py`, one in
`simulator/scenarios/scenario_definitions.py`.

Stale/misleading documentation (not a code gap, a doc gap): `docs/razorpay-integration.md`
§9 ("Phase 1 has no live Razorpay integration yet") directly contradicts §4/§7 of the same
document, which describe real, tested adapters.

## Confirmed P0 defect (not previously documented anywhere)

Payment-link-driven recovery (`SMART_RETRY`/`DELAYED_RETRY`/`CUSTOMER_ACTION_REQUEST`) cannot
resolve its originating `RecoveryCase` when the customer pays: the new payment gets a new
`razorpay_payment_id`, unlinked from the case's original (failed) `payment_id`. Only the
narrow same-`payment_id` UPI-retry path resolves today. `RecoveryCase` has no
`actual_recovered_amount` column — the dashboard's "recovered" figure is the case's original
at-risk amount, not a verified actual amount. This is the subject of the primary P0 fix in
this pass.

## Razorpay documentation verification (this session)

Fetched live from `razorpay.com/docs` and `razorpay.com/buildathon`:
- Track 03 requirements unchanged from what `docs/razorpay-integration.md` already states:
  public repo + 5-minute video + architecture docs; "measured money recovered across a
  batch, with compliant escalation, stopping rules, and an audit trail."
- **Confirmed**: the `payment_link.paid` webhook event fires with `contains:
  ["payment_link", "order", "payment"]` — i.e. `payload.payment_link.entity` (including
  `reference_id` and `notes`) and `payload.payment.entity` (the actual captured payment)
  arrive together in one delivery. This is the mechanism the P0-1 fix uses as the primary
  correlation signal, since RecoveryOS already sets a deterministic
  `reference_id=f"recoveryos-{recovery_action.id}"` on Payment Link creation
  (`smart_retry_handler.py`) — resolving the open question flagged during design.
