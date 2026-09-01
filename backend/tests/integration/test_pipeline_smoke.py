"""Documents the intended end-to-end flow this codebase is building toward. Skipped, not
deleted or left unwritten — a structural seam that later phases turn into a real test as each
service stops being a stub:

  payment.failed webhook -> ingestion (Phase 1, real) -> state reconstruction (Phase 2)
  -> revenue signal detection -> recovery_opportunity (Phase 5)
  -> recovery_case created, DETECTED -> ELIGIBLE -> ANALYZING (Phase 5)
  -> ML prediction + AI diagnosis, both agent_decisions rows (Phase 6/8)
  -> optimizer selects candidate, ACTION_PROPOSED (Phase 6)
  -> policy evaluates, POLICY_APPROVED (Phase 7)
  -> executor runs the handler, recovery_action SUCCEEDED (Phase 9/10)
  -> a later payment.captured webhook reconciles the case to SUCCEEDED (Phase 9)
  -> every hop has a corresponding audit_logs row with a shared correlation_id (Phase 12)

See docs/track-alignment.md for how this maps to the Track 03 requirements and
docs/demo-script.md (Phase 21) for how this same flow is demonstrated live.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="pipeline services (state reconstruction onward) are stubbed until Phase 2+")
def test_full_pipeline_payment_failure_to_recovery():
    raise AssertionError("not yet implemented — see module docstring")
