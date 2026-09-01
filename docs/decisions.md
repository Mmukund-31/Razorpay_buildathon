# Engineering Decisions (ADRs)

Numbered for reference from code comments (`docs/decisions.md ADR-00X`). Each one states the
decision, why, and what the alternative would have cost.

## ADR-001 — VARCHAR + CHECK instead of native Postgres ENUM types

**Decision**: every status/enum column is `VARCHAR` with a `CHECK (... IN (...))` constraint,
not a Postgres `ENUM` type. `backend/app/domain/enums.py` is the single Python source of
truth; the CHECK constraint mirrors it as defense-in-depth, not as an independent definition.

**Why**: Postgres `ENUM` types require `ALTER TYPE ... ADD VALUE` migrations to extend (and
that statement can't run inside a transaction in older Postgres versions), which is real
friction for a system whose state machines are still being refined across 21 phases. A
`CHECK` constraint is a normal, transactional `ALTER TABLE`.

**Cost of the alternative**: marginally smaller storage per row and slightly stricter typing
at the DB layer — not worth the migration friction here.

## ADR-002 — No Redis; a DB-polling background worker instead

**Decision**: a single in-process asyncio task polls `webhook_events` for `PENDING` rows,
ordered by `(razorpay_created_at, sequence_id)`, instead of a Redis-backed queue.

**Why**: durability comes from `webhook_events.processing_status`, not in-memory queue state
— a crashed/restarted worker just re-polls. That's the correctness property that matters, and
it doesn't require Redis to get it. A single-instance buildathon deployment gains nothing
from an extra service beyond Postgres; `docker-compose.yml` stays at two services. The
worker's interface (`app/core/background_worker.py`) is isolated enough that swapping in
Redis+RQ/Celery later, if real concurrent-worker scale is ever needed, is a drop-in
replacement, not a rewrite — see `docs/architecture.md`'s scaling-path note.

**Cost of the alternative**: Redis would signal "infra maturity" to a reviewer skimming
`docker-compose.yml`, but that's optimizing for appearance, not for the problem — see
principle #61 in the product spec ("do not optimize for visual complexity").

## ADR-003 — Razorpay logic stays behind two adapters, never scattered

**Decision**: all Razorpay-specific HTTP logic lives in `app/integrations/razorpay_client.py`
(auth, retry policy) plus `payment_link_adapter.py` and `subscription_adapter.py`. No other
module — not services, not the optimizer, not the AI diagnostician — is allowed to import
`httpx` or construct a Razorpay request directly.

**Why**: this is what makes `docs/razorpay-integration.md`'s real-vs-simulated table
enforceable rather than aspirational — if Razorpay calls could originate from five different
files, "only the executor calls Razorpay" would be a claim nobody could verify by reading the
code. It also makes the eventual `SimulatorGateway` swap (same interface, fake backend, used
by the benchmark pipeline) a clean substitution instead of a search-and-replace exercise.

## ADR-004 — The simulator drives the real pipeline, never a parallel fake one

**Decision**: `simulator/generators/*.py` produce Razorpay-shaped webhook payloads and POST
them at `POST /api/webhooks/razorpay` — the exact endpoint real Razorpay test-mode traffic
hits. There is no separate "simulated recovery case" code path.

**Why**: the product spec is explicit about this ("the same recovery engine must process
simulator events... do not create a separate fake logic path just for the demo") and it's the
only way a demo can be trusted — if the failure-storm demo ran through different code than
production, showing it working would prove nothing about the real system.

## ADR-005 — LLM provider: Anthropic, kept behind a swappable interface

**Decision**: `LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY` are environment-configurable;
`app/agents/ai_diagnostician.py`'s real implementation calls Anthropic's Messages API
(`claude-sonnet-5` by default) via the `anthropic` SDK. The call itself lives in one
isolated function (`_call_llm`), so swapping providers means replacing that one function, not
touching the validation/retry/circuit-breaker logic around it.

**Why Anthropic**: this project is built with Claude Code, and Claude's models are strong at
reliably following a strict-JSON-only instruction, which is what this call is graded on more
than raw reasoning quality — the diagnosis task is bounded and structured, not open-ended.

**Verified without a real API key**: every test in `tests/unit/test_ai_diagnostician.py`
mocks `_call_llm` directly rather than hitting the network, so the validation/retry/circuit-
breaker contract is fully tested independent of having Anthropic credentials configured in
any given environment — including this one.

## ADR-006 — Policy thresholds, and the one real recalibration that happened

**Decision**: `MIN_EXPECTED_VALUE=0.05` (5% of amount), `MAX_RETRIES=3`,
`RECOVERY_WINDOW_HOURS=168` (7 days), and a small placeholder intervention-cost table
(₹0.20 for SMS/payment-link actions, ₹5 for the simulated voice call, proportionally small
risk costs for customer-facing channels) are documented starting points, not values fit to
data — there is no real cost data to fit them to.

**`MIN_CONFIDENCE` is the one threshold that was actually corrected against real evidence.**
The original placeholder (0.55) was picked before any model existed. Once the real LightGBM
model was trained and the full benchmark (docs/ml-evaluation.md) was run against it, 0.55
turned out to reject the overwhelming majority of candidates — the model's predicted
probabilities center around the dataset's ~24% base recovery rate, so a 0.55 bar implicitly
assumed something close to a coin-flip model, which this correctly is not. Recalibrated to
`0.15` (roughly two-thirds of the base rate) based on the model's actual output distribution,
then the benchmark was run once more and the result reported honestly — RecoveryOS still
doesn't win on raw recovered revenue at this corrected threshold (see docs/ml-evaluation.md).
This ordering matters: the threshold was fixed because it was demonstrably miscalibrated
against the model's real behavior, not adjusted afterward to chase a better-looking benchmark
number — the result after the fix is reported as-is, whatever it turned out to be.

Production next step: derive `MIN_CONFIDENCE`/`MIN_EXPECTED_VALUE` directly from the
validation set's precision/recall tradeoff (now possible — the benchmark harness exists and
is reproducible) rather than a single hand-picked number, and revisit the placeholder cost
table once any real intervention-cost data exists.

## ADR-007 — Reviving `outcome_service.py` as the real reconciliation engine, and
`reference_id` (not `notes`) as the correlation key

**Context**: the dominant real-world recovery path (SMART_RETRY/DELAYED_RETRY/
CUSTOMER_ACTION_REQUEST) resolves to a fresh Razorpay Payment Link, so the payment that
eventually gets captured has a different `razorpay_payment_id` than the case's original
failed payment. Before this hardening pass, `pipeline_orchestrator.py::_resolve_if_captured`
only checked `RecoveryCaseRepository.get_live_case_for_payment(payment.id)` — which can never
match a brand-new payment id — so this entire class of recovery silently never resolved.
`app/services/outcome_service.py` existed as a dead stub the whole time.

**Decision**: revive `outcome_service.py` as the real `reconcile_outcome()` — a distinct
module from `pipeline_orchestrator.py`, matching the existing pattern where
`analysis_service.py`/`execution_service.py` are separate from the orchestrator that chains
them. `pipeline_orchestrator.py::_resolve_if_captured` now just delegates to it.

**Correlation key**: `reference_id`, not `notes`. RecoveryOS already sets a deterministic
`reference_id = f"recoveryos-{recovery_action.id}"` at Payment Link creation
(`app/domain/recovery_action_reference.py`), and this is what Razorpay's verified
`payment_link.paid` webhook echoes back on `payload.payment_link.entity.reference_id`. This
was chosen over relying on Payment Link `notes` propagating onto the resulting `payment`
entity, because `reference_id` depends only on what RecoveryOS itself sends and Razorpay
returns unchanged — it does not depend on an unverified "does Razorpay copy payment-link
notes onto the payment" behavior. A plain `payment.captured` event with no `payment_link`
entity (e.g. a merchant not subscribed to `payment_link.paid`) genuinely carries no
correlation information; this is a disclosed limitation (`docs/limitations.md`), not silently
papered over.

**Idempotency**: `actual_recovered_amount` is written by a conditional `UPDATE ... WHERE
actual_recovered_amount IS NULL` — the same "write once, guarded by a DB predicate" pattern
`PaymentRepository`/`RecoveryCaseRepository` already use elsewhere, not a new mechanism.

## ADR-008 — The idempotency-key UNIQUE constraint, not the case-level optimistic lock, is
what actually prevents a double `execute()`

**Context discovered while adding a concurrency test** (`test_execute_concurrency.py`): two
simultaneous `POST /recovery-cases/{id}/execute` requests could raise an unhandled
`IntegrityError` (surfaced as a 500) instead of the intended idempotent no-op. The case-level
optimistic lock (`recovery_cases.version`) is NOT sufficient on its own to prevent this: when
the losing request's `recovery_case_service.transition()` call retries after losing its
`WHERE version=:expected` race, it re-reads the case and correctly observes the WINNER's now-
`EXECUTING` status — meaning **both** callers legitimately reach the `RecoveryAction` insert
with the identical `idempotency_key`, and only the database's own UNIQUE constraint stops the
second one from persisting.

**Decision**: `execution_service.py`'s `_insert_action_or_recover_from_race()` catches that
`IntegrityError`, rolls back the losing session's failed insert attempt, and re-fetches the
case fresh — treating a lost DB-level race exactly like the existing pre-insert
`get_by_idempotency_key()` hit (a safe, idempotent no-op), never an unhandled 500. This is the
concrete fix for "can this accidentally execute an action (and thus create a duplicate
Payment Link) twice" — matching the product spec's own instruction to use database-level
constraints, not application-level checks alone, as the real enforcement.

## Why FastAPI

Async-native (matters for the webhook ack-under-5-seconds requirement and the DB-polling
worker running alongside request handling), Pydantic integration gives the AI/policy
structured-output validation this system leans on heavily, and automatic OpenAPI generation
keeps the API contract honest without hand-maintained docs.

## Why PostgreSQL

JSONB for the genuinely semi-structured fields (`raw_entity`, `payload`, `reason_codes`,
`metrics`) without giving up relational integrity everywhere else; partial unique indexes are
what make "at most one live recovery_case per payment" a database-enforced guarantee instead
of an application convention; and it's the natural pairing with SQLAlchemy 2.0's async engine.

## Why tabular ML (LightGBM/XGBoost) over a deep model

The feature set (`ml/features/feature_definitions.py`) is small, structured, and tabular —
amount, retry count, categorical failure class, historical rates. Gradient-boosted trees are
the well-established strong baseline for exactly this shape of problem, they're fast enough
to retrain during a buildathon iteration loop, and — importantly for `docs/ml-evaluation.md`'s
calibration requirements — their probability outputs are easier to calibrate and explain than
a deep model's, which matters when a probability feeds directly into a financial
expected-value calculation a human reviewer needs to trust.

## Why an LLM at all, given the ML model already predicts recovery probability

The ML model answers "how likely is this to recover" — a single number. It cannot explain
*why* a payment failed in a form a customer-facing message can use, cannot reason about
context that isn't in the training features (e.g. an unusual `error_description` string),
and cannot generate the Hinglish voice script content. The AI Diagnostician's job is
classification and language generation, strictly bounded by structured output — it augments
the optimizer's inputs, it does not replace the ML probability estimate or make the financial
decision.

## Why the LLM cannot execute actions (restated as an engineering, not just a policy, decision)

Beyond the product requirement, this is a straightforward reliability argument: LLM outputs
are not deterministic and can be adversarially influenced by attacker-controlled input (a
customer's `metadata.name` field, for instance — see the prompt-injection defense in
`app/agents/prompts.py`). A system where untrusted text can influence which HTTP request gets
sent to a payments API is not one a senior engineer would sign off on, regardless of how good
the model is. Structured output validated by Pydantic, dispatched through an allowlisted enum,
gated by a separate deterministic policy engine, is the standard mitigation — and it's
testable in a way "trust the model" isn't.

## Why not multi-agent (in the "many autonomous LLM agents negotiating" sense)

The pipeline has exactly one LLM call site (`ai_diagnostician.py`) by design. Multiple
independent agents debating a financial decision would add latency, cost, and
non-determinism without a corresponding gain — the actual hard problem here (bounding what an
AI-influenced system can do to money) is solved by the policy/execution boundary, not by
adding more models. "Number of AI agents" is explicitly not an optimization target (product
spec §61).

## Why synthetic data instead of scraping/collecting real transaction data

No real merchant transaction history is available for a buildathon project, and using real
customer PII would be inappropriate regardless. A deterministic-seed synthetic generator with
documented, meaningful feature relationships (Phase 3) is the standard, defensible approach
for this kind of demonstration ML problem, and it's the only way the dataset's ground truth
(`actual_recovered`, `recovery_time`, etc.) can exist at all — that information doesn't exist
for hypothetical real transactions.

## Why a simulator instead of only real Razorpay test-mode traffic

Real test-mode traffic requires manually driving a browser checkout per transaction — it
cannot produce the "thousands of events" scale the batch-benchmark requirement implies. The
simulator closes that gap while (per ADR-004) never diverging from the real pipeline.

## Why idempotency keys everywhere a financial action can happen

Razorpay's webhook delivery is at-least-once by design (not a bug to work around, a
documented guarantee to design for). Any code that assumes "this event arrives exactly once"
will eventually double-act on a retried delivery. `webhook_events.razorpay_event_id` and
`recovery_actions.idempotency_key` are both `UNIQUE` constraints, not just application checks,
because the failure mode (a duplicate SMS, a duplicate Payment Link, worse) is exactly the
kind of thing that shouldn't depend on application code being bug-free.

## Why abstention is a first-class state, not an error

A system that must always output *some* action under uncertainty will eventually take a bad
one. Making `ABSTAINED` a normal terminal state — reachable when ML and AI both fail to
produce a valid signal — means "we don't know" is a legitimate, auditable outcome instead of
something the code has to work around or silently paper over with a default action.

## Why a modular monolith instead of microservices

One deployable backend service with clean internal module boundaries (`api/`, `domain/`,
`services/`, `policies/`, `executors/`, `integrations/`, `repositories/`) gets almost all the
benefit of service separation — enforced boundaries, testable units, a place for every
responsibility — without the operational cost of running and coordinating multiple services
for a buildathon-scale deployment. `docs/architecture.md`'s scaling path describes where this
would split if it ever needed to (the background worker is the natural first extraction), but
building that split now would be infrastructure for appearance, which the product spec
explicitly warns against.
