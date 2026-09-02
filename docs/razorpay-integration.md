# Razorpay Integration — Verified Facts, Real vs Simulated

This document is Phase 0's deliverable: every claim below was checked against the live
Razorpay documentation (and, where docs disagreed with search-engine summaries, against the
canonical `razorpay.com/docs` pages directly) before any code was written. **Nothing here is
assumed.** Where the API genuinely can't do something the product spec implies, that
limitation is stated plainly and the workaround is labeled as a workaround, not presented as
the thing it isn't.

## 1. The Buildathon bar (Track 03 — AI Revenue Recovery)

From the live buildathon page: detect revenue at risk → determine the right intervention →
execute a **bounded** recovery workflow, and show **measured money recovered across a batch,
with compliant escalation, stopping rules, and an audit trail**. Example directions listed:
payment degradation recovery, checkout drop-off recovery, failed-subscription recovery, B2B
receivables chasing, mandate retry sequencing, **Hinglish voice recovery**, promise-to-pay
tracking. Submission requirements: a public repository, a 5-minute pitch video, and
architecture documentation.

## 2. Webhooks

- **Signature**: `X-Razorpay-Signature` header = hex(`HMAC-SHA256(raw_request_body,
  webhook_secret)`). Verification **must** run against the raw, unparsed body — parsing first
  and re-serializing changes byte formatting and silently breaks every signature. See
  `backend/app/integrations/webhook_verifier.py`.
- **Idempotency**: `x-razorpay-event-id` header, unique per event. RecoveryOS enforces this
  with a `UNIQUE` constraint on `webhook_events.razorpay_event_id`, not just an application
  check — a duplicate insert raises `IntegrityError`, caught and acked as an idempotent no-op.
- **Delivery semantics**: at-least-once, exponential backoff retries on non-2xx for up to 24
  hours (the webhook auto-disables after that). This is why the ingestion endpoint does
  nothing but verify + persist + ack — it must respond within ~5 seconds, so ML/LLM
  processing happens asynchronously in the background worker.
- **Ordering**: not guaranteed. RecoveryOS's payment state machine guards every transition
  with `(last_event_created_at, last_event_sequence_id)` so a delayed, out-of-order delivery
  can never overwrite newer state.

## 3. Payment webhook events

`payment.authorized`, `payment.captured`, `payment.failed`,
`payment.downtime.{started,updated,resolved}`, `order.paid`. Two verified quirks the state
machine specifically encodes:

- `payment.failed` does **not** fire on a failure during the very first checkout
  authorization attempt — only once an order/payment entity already exists and a *subsequent*
  attempt fails.
- A `payment.failed` can be followed later by a `payment.captured` for the **same**
  `payment_id` — most commonly on UPI, where a customer enters a wrong PIN, corrects it, and
  succeeds inside their UPI app. RecoveryOS's state machine explicitly allows `FAILED →
  CAPTURED`; treating this as illegal would have been a real bug.

Error payload shape: `code`, `description`, `source` (customer/bank/gateway/network), `step`,
`reason` (machine-handleable), plus `metadata.payment_id`/`order_id`. RecoveryOS's
`failure_class` and `reason_codes` are derived from `reason`, not invented.

## 4. The critical limitation: there is no "retry a failed payment" API

This is the single most important verified fact in this document, because it shapes the
entire intervention-execution design.

**Razorpay has no API to force-retry a failed one-time payment server-side.** The Payments API
lets you fetch a payment and capture an *authorized* one — capture moves `authorized →
captured`, it does not resurrect a `failed` payment. The only real way to recover a one-time
payment is to get the customer to complete a **new** checkout.

The mechanism for that is the **Payment Links API** (`POST /v1/payment_links`), verified
request/response shape:

- Request: `amount`, `currency`, `reference_id`, `description`, `customer.{name,email,
  contact}`, `notify.{sms,email}` (booleans — Razorpay sends the notification itself),
  `expire_by` (unix timestamp, 15 min to 6 months out), `callback_url` + `callback_method`,
  `notes` (up to 15 key-value pairs), `accept_partial` (boolean).
- Response: `id` (`plink_...`), `short_url`, `status` (`created` / `partially_paid` / `paid` /
  `expired` / `cancelled`).

**`accept_partial` is always sent as `false`** (`payment_link_adapter.py`). Razorpay Payment
Links natively support letting a customer settle less than the requested amount, moving
`status` to `partially_paid` rather than `paid` — RecoveryOS never wants this for a recovery
link: the amount was already computed by the optimizer/policy as the exact figure a
policy-approved action is allowed to collect, and `outcome_service.reconcile_outcome()` has no
branch for "partially resolved" (see `docs/limitations.md`). Setting this explicitly, rather
than relying on Razorpay's default, is what makes that assumption safe to depend on.

So **SMART_RETRY**, **DELAYED_RETRY**, and the payment-link half of
**CUSTOMER_ACTION_REQUEST** are all implemented as *creating a fresh Payment Link and letting
Razorpay deliver it* — never as a fictitious retry call.

## 5. Subscriptions

- Card/UPI auto-retry is entirely Razorpay-managed, on a T+0..T+3 day cycle: the subscription
  moves to `pending` after the first failed charge, and to `halted` once all retries are
  exhausted. RecoveryOS does not (and cannot) trigger these retries itself.
- The real merchant-side recovery levers once `halted`: **`subscription_card_change`** (a
  Razorpay-hosted page link letting the customer update their card) and **manually charging
  an `issued` invoice** — which Razorpay explicitly does **not** support for domestic cards.
- Relevant webhooks: `subscription.charged`, `subscription.pending`, `subscription.halted`.

## 6. Test Mode

Separate test API key pair, a mock bank page with Success/Failure buttons, test UPI IDs
`success@razorpay` / `failure@razorpay` for deterministic outcomes, and dedicated test card
numbers for specific error scenarios. No real money moves in test mode under any
circumstance. `.env.example` documents `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` /
`RAZORPAY_WEBHOOK_SECRET` as test-mode-only.

## 7. Intervention actions → real vs simulated, one by one

| Action | Real or simulated | Mechanism | Code |
|---|---|---|---|
| `SMART_RETRY` | **Real** | Fresh, exact-amount Payment Link, short `expire_by`, Razorpay-sent notify. For subscriptions: `subscription_card_change` or manual invoice charge. | `app/integrations/payment_link_adapter.py`, `app/integrations/subscription_adapter.py` |
| `DELAYED_RETRY` | **Real** | Identical mechanism, fired later once `recovery_actions.scheduled_for` is reached. | same adapters, scheduled path |
| `CUSTOMER_NOTIFICATION` | **Simulated** | Informational message only, no new Payment Link. | `app/services/communication/text_provider.py` |
| `CUSTOMER_ACTION_REQUEST` | **Hybrid** | Real Payment Link / `subscription_card_change` call **plus** a simulated explanatory message. | `payment_link_adapter.py` + `text_provider.py` |
| `HINGLISH_VOICE` | **Simulated** | The signature feature. No real telephony integration exists in this build — a `CommunicationProvider`-conforming `SimulatedVoiceProvider` produces a logged, scenario-driven transcript. Requires `consent_recorded=true` as an executor precondition, not a UI-only gate. | `app/services/communication/simulated_voice_provider.py` |
| `ESCALATION` | **Simulated** | An audit log entry + dashboard flag. No real paging/ops integration. | `app/executors/handlers/escalation_handler.py` |
| `NO_ACTION` | No integration | Deliberate no-op, logged for auditability. | `app/executors/handlers/no_action_handler.py` |

## 8. The never-conflate rule

Thousands of synthetic events (the scale the batch-benchmark requirement implies) cannot
realistically be driven through real browser checkouts. So:

- The **benchmark / ML training pipeline** runs entirely against a synthetic dataset and the
  simulator, exercising the exact same domain/policy/executor code as production but through
  a fake gateway adapter implementing the same interface as the real one. It **never** calls
  a real Razorpay API.
- The **live single-case demo** may optionally exercise one **real** test-mode Payment Link
  creation call, to prove the integration genuinely works end-to-end.

Nothing in the UI, the docs, or the demo script is allowed to imply a simulated outcome came
from a real API call, or that a real API call's result was fabricated. Where a screen shows a
number, it traces back to either a real API response or a clearly-labeled simulated one — see
`docs/decisions.md`'s "no fabricated metrics" rule.

## 9. Current implementation status (superseding the original Phase 1 draft of this section)

Every adapter/executor this document's §7 table describes is implemented and tested, not a
stub: `webhook_verifier.py` (real signature verification), the webhook ingestion endpoint
(real signature check + idempotent persistence + background-worker processing),
`payment_link_adapter.py`/`subscription_adapter.py` (real Razorpay API calls, gated behind
credential availability via `gateway_factory.py` — falling back to `simulator_gateway.py`
only when `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` aren't configured, per §7/§8's real-vs-
simulated rule), and `outcome_service.py` (real payment-link recovery correlation — §10
below). Bounded retry/backoff on transient failures (timeout, 429, 5xx — never 4xx) is
implemented in `razorpay_client.py` and tested against all three failure modes independently
(`tests/integration/test_razorpay_adapter.py`), not just the generic 5xx case.

## 10. Payment-link recovery correlation

Recovering a one-time payment always means the customer pays through a **new** Payment Link
(§4), so the resulting `payment.captured`/`payment_link.paid` webhook carries a brand-new
`razorpay_payment_id`, unrelated to the original failed payment. Verified against
`razorpay.com/docs`: the **`payment_link.paid`** webhook event fires with `contains:
["payment_link", "order", "payment"]` — i.e. `payload.payment_link.entity` (including
`reference_id` and `notes`) and `payload.payment.entity` (the actual captured payment) arrive
together in a single delivery.

RecoveryOS sets a deterministic `reference_id = f"recoveryos-{recovery_action.id}"`
(`app/domain/recovery_action_reference.py`) when creating the recovery Payment Link
(`smart_retry_handler.py` — reused by `DELAYED_RETRY`/`CUSTOMER_ACTION_REQUEST`). When
Razorpay echoes it back on `payment_link.paid`, `state_reconstruction_service.py` resolves
`payments.recovery_action_id` from it (idempotently — set once, regardless of delivery
order), and `app/services/outcome_service.py::reconcile_outcome()` uses that to find the
originating `RecoveryCase`, verify it's still eligible (not already terminal, matching
currency), write `actual_recovered_amount` exactly once via an `IS NULL`-guarded conditional
UPDATE, and drive the case to `SUCCEEDED` through the normal state machine — never a parallel
status-setting path. A plain `payment.captured` event (no `payment_link` entity — e.g. if a
merchant hasn't subscribed to `payment_link.paid`) carries no correlation information at all;
in that case the payment is reconstructed correctly but cannot be traced back to a recovery
case, a known, disclosed limitation (see `docs/limitations.md`) rather than a silently
swallowed failure.

The narrower **same-`payment_id`** case (the verified UPI wrong-PIN-then-retry quirk, §3)
needs no correlation at all — `RecoveryCaseRepository.get_live_case_for_payment()` already
finds it directly, and this path is tried first in `reconcile_outcome()`.
