"""The Outcome Engine: reconciles a later signal (a fresh payment.captured webhook, or a
poll against the Razorpay Payments API) back onto an EXECUTING/SCHEDULED recovery_case,
driving it to SUCCEEDED or FAILED. STUB in Phase 1.

TODO(phase-9/13): implement. Must always re-check `payments.status` freshly (never trust a
cached flag) before writing an outcome, matching the recovery_case_state_machine's
payment_captured guard.
"""


async def reconcile_outcome(recovery_case_id) -> None:
    raise NotImplementedError("TODO(phase-9)")
