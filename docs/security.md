# Security

## Webhook signature validation

`app/integrations/webhook_verifier.py`: `hex(HMAC-SHA256(raw_body, webhook_secret))`,
constant-time compared (`hmac.compare_digest`) against `X-Razorpay-Signature`. Verification
runs against the **raw bytes** of the request body (`await request.body()` in
`app/api/webhooks.py`), captured before any JSON parsing — parsing and re-serializing can
change byte-for-byte formatting and silently break every signature, so the raw bytes are what
get checked and what get persisted to `webhook_events.raw_body`.

An invalid signature returns `400 {"code": "INVALID_WEBHOOK_SIGNATURE", ...}` — the request is
never processed, never persisted past the ingestion attempt.

## Secrets handling

- All configuration through `app/core/config.py`'s `Settings` (pydantic-settings), reading
  from environment variables / `.env`. No module reads `os.environ` directly anywhere else in
  the codebase.
- `.env` is gitignored; only `.env.example` (placeholder values) is committed.
- `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` default to empty strings — `gateway_factory.py`
  falls back to the simulator adapters when they're unset, rather than failing or, worse,
  attempting a real call with empty credentials.
- `RAZORPAY_WEBHOOK_SECRET` has a **non-empty** local-development default
  (`recoveryos-local-dev-webhook-secret`), explicitly documented as not a real Razorpay
  secret — it exists so the simulator can sign events and prove the real
  `POST /api/webhooks/razorpay` verification path end-to-end without requiring any
  configuration, never by bypassing that path (see docs/decisions.md ADR-004).
- Structured logs never include secret values — `configure_logging()`'s formatter only ever
  receives the fields explicitly passed via `extra=`, and no call site in the codebase passes
  a credential.
- Audit-log immutability: `AuditLogRepository` exposes only `add()`/read methods — there is no
  update/delete code path anywhere, verified mechanically by
  `tests/unit/test_audit_log_immutability.py` (inspects the class's public methods directly,
  so a future edit that adds one is caught, not just documented against). A DB-level
  `REVOKE UPDATE, DELETE` for a dedicated least-privilege role remains a recommended
  production hardening step beyond what this build's `docker-compose.yml` sets up, to keep
  local/demo setup friction-free — see docs/decisions.md ADR-001's related note.

## Input validation

Every API request body is a Pydantic model with `extra="forbid"`
(`EvaluateRequest`/`ExecuteRequest` in `app/api/recovery_cases.py`, the simulator endpoints'
`Body(...)` parameters). Every AI output and every policy decision is Pydantic-validated
before being trusted (see docs/ai-design.md). Path/query parameters are typed
(`uuid.UUID`, `int`, `datetime`) so FastAPI rejects malformed input before a handler ever runs.

## SQL injection surface

SQLAlchemy Core/ORM exclusively — every query in the codebase is built with
`select()`/`update()`/parameterized `.where()` clauses. The one place raw SQL text appears is
`text("SELECT 1")` (health checks, migration env) — a fixed literal with no interpolated
input. No f-string or `%`-formatted SQL exists anywhere in the codebase.

## The execution-boundary control (restated as a security control, not just an architecture
one)

`ActionExecutor` is the only module permitted to import the Razorpay adapters or a
`CommunicationProvider` implementation (see docs/architecture.md). Combined with the
`ActionType` allowlist (Pydantic enum + DB `CHECK` constraint) and the mandatory
`policy_evaluation_id` FK, this means: even a fully successful prompt injection that got the
LLM to emit a well-formed-but-malicious `AIDiagnosisOutput` still can only name one of 7
allowlisted, pre-defined, non-parameterized actions — there is no field in that schema an
attacker could use to specify an amount, a destination, or a raw API call. The blast radius of
a compromised or manipulated LLM output is bounded by design, not by hoping the model behaves.

## Prompt-injection defenses

See docs/ai-design.md's dedicated section — the untrusted-data wrapper, the schema's
`extra="forbid"`, and the enum-constrained `recommended_action` field are the three layers,
each independently tested.

## Error handling

`app/core/errors.py`'s global exception handlers return `{"code", "message", "request_id"}`
for every error path — `AppError` (domain errors), `HTTPException`, `RequestValidationError`,
and a catch-all `Exception` handler that logs the full traceback server-side
(`logger.exception`) but returns only the generic message and a `request_id` to the client. No
stack trace, file path, or internal exception text is ever included in an API response.

## Dependency posture

Backend dependencies are pinned by minimum version in `backend/pyproject.toml`; the ML stack
(`scikit-learn`, `lightgbm`, `pandas`, `joblib`) and the Anthropic SDK are backend
dependencies (not optional extras) since `ml_predictor.py`/`ai_diagnostician.py` need them at
runtime, not just for offline training. `respx` (dev-only) mocks all HTTP-layer tests — no
test in this suite makes a real network call to Razorpay or Anthropic.

## What a production hardening pass would still add

- The DB-role `REVOKE` for audit-log immutability, applied via migration rather than left as
  an application-layer-only guarantee.
- Rate limiting on the public webhook endpoint (currently relies on Razorpay's own retry
  discipline and the DB's connection pool as an implicit backstop).
- Request-level authentication/authorization on the operator-facing API surface
  (`/api/recovery-cases/*`, `/api/simulator/*`) — this build is single-tenant with no auth
  layer, appropriate for a buildathon demo, explicitly not for a multi-tenant production
  deployment (see docs/decisions.md's frontend-auth note).
