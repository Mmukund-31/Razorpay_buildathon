import { useState } from "react";
import { apiPost, ApiRequestError } from "../api/client";

interface ActionButton {
  label: string;
  description: string;
  run: () => Promise<unknown>;
}

const SCENARIOS: { name: string; label: string; description: string }[] = [
  {
    name: "bank_failure",
    label: "Bank Failure",
    description: "A payment declined by the issuing bank — should be detected and recovered normally.",
  },
  {
    name: "api_timeout",
    label: "Razorpay Timeout",
    description: "A gateway-timeout failure — exercises the bounded-retry logic in the Razorpay adapter.",
  },
  {
    name: "duplicate_webhook",
    label: "Duplicate Webhook",
    description: "The exact same event id delivered twice — the second must be an idempotent no-op.",
  },
  {
    name: "out_of_order_webhook",
    label: "Out-of-Order Events",
    description: "A newer event delivered before an older one — the older must be rejected as stale.",
  },
  {
    name: "already_recovered_payment",
    label: "Already Recovered Payment",
    description: "A payment.captured arrives after payment.failed — the case must resolve to SUCCEEDED, never be retried.",
  },
];

export default function Simulation() {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  function appendLog(line: string) {
    setLog((prev) => [`${new Date().toLocaleTimeString()}  ${line}`, ...prev].slice(0, 50));
  }

  async function run(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    try {
      const result = await fn();
      appendLog(`${name} → ${JSON.stringify(result)}`);
    } catch (err) {
      appendLog(`${name} → ERROR: ${err instanceof ApiRequestError ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  }

  const stormButtons: ActionButton[] = [
    {
      label: "Generate Failure Storm (100 events)",
      description: "Posts 100 realistic synthetic payment.failed webhooks through the real ingestion pipeline.",
      run: () => apiPost("/simulator/failure-storm", { count: 100, seed: Date.now() % 100000 }),
    },
  ];

  return (
    <div className="max-w-3xl space-y-6">
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-300">Failure Storm</h2>
        <p className="mb-3 text-xs text-slate-500">
          Every button below drives the SAME production pipeline real Razorpay webhooks use —
          see docs/decisions.md ADR-004. Results show up in the Command Center and Recovery
          Queue within a few seconds as the background worker processes them.
        </p>
        {stormButtons.map((b) => (
          <button
            key={b.label}
            disabled={busy !== null}
            onClick={() => run(b.label, b.run)}
            className="rounded bg-sky-700 px-3 py-1.5 text-sm text-white hover:bg-sky-600 disabled:opacity-50"
          >
            {busy === b.label ? "Running…" : b.label}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-300">Failure Injection Scenarios</h2>
        <div className="space-y-3">
          {SCENARIOS.map((s) => (
            <div key={s.name} className="flex items-start justify-between gap-4 border-t border-slate-800 pt-3 first:border-t-0 first:pt-0">
              <div>
                <p className="text-sm text-slate-200">{s.label}</p>
                <p className="text-xs text-slate-500">{s.description}</p>
              </div>
              <button
                disabled={busy !== null}
                onClick={() =>
                  run(s.name, () => apiPost("/simulator/scenario", { scenario_name: s.name, params: {} }))
                }
                className="shrink-0 rounded border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
              >
                {busy === s.name ? "Running…" : "Run"}
              </button>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-slate-500">
          Bad-AI-recommendation and low-confidence scenarios are demonstrated in the test
          suite (tests/unit/test_policy_engine.py's bad-AI-demo test,
          tests/unit/test_ai_diagnostician.py) rather than as buttons here — they are policy
          decisions over live case state, not standalone webhook events.
        </p>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-300">Log</h2>
        <div className="max-h-64 space-y-1 overflow-y-auto font-mono text-xs text-slate-400">
          {log.length === 0 && <p className="text-slate-600">No actions run yet.</p>}
          {log.map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
      </div>
    </div>
  );
}
