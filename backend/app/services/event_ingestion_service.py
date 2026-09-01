"""Historical note: this module's originally-planned responsibility (verify + dedupe +
persist a webhook, then hand it to state reconstruction) ended up split across two real
places instead of living here — `app/api/webhooks.py` owns verify+dedupe+persist (it has to,
to ack within Razorpay's ~5s window), and `app/services/pipeline_orchestrator.py` owns
everything from state reconstruction onward, called by `app/core/background_worker.py`'s
poll loop. Kept as an empty module (rather than deleted) so the repo layout in
docs/architecture.md stays accurate to what actually exists.
"""
