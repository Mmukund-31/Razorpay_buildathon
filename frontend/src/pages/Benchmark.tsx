import { useApi } from "../hooks/useApi";
import type { BenchmarkExperiment } from "../api/types";

const KEY_METRICS = [
  "recovered_revenue",
  "recovery_rate",
  "revenue_per_intervention",
  "unnecessary_action_rate",
];

function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="h-2 w-full rounded bg-slate-800">
      <div className="h-2 rounded bg-sky-600" style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function Benchmark() {
  const { data, error, loading } = useApi<{ experiments: BenchmarkExperiment[] }>(
    "/analytics/benchmark",
    0,
  );

  if (loading && !data) return <p className="text-slate-400">Loading…</p>;
  if (error) return <p className="text-rose-400">Failed to load benchmark: {error}</p>;

  const experiments = data?.experiments ?? [];
  if (experiments.length === 0) {
    return (
      <div className="max-w-2xl rounded-lg border border-slate-800 bg-slate-900 p-6 text-sm text-slate-400">
        No benchmark run recorded yet. Run{" "}
        <code className="text-slate-300">python scripts/run_simulator.py</code> or{" "}
        <code className="text-slate-300">
          python -m simulator.benchmark.baseline_runner
        </code>{" "}
        to compare Always Retry, Static Rules, ML Only, and RecoveryOS on the synthetic
        held-out set. Nothing here is ever hand-authored — see docs/decisions.md.
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-6">
      {KEY_METRICS.map((metric) => {
        const rows = experiments
          .filter((e) => metric in e.metrics)
          .map((e) => ({ name: e.baseline_type, value: e.metrics[metric] }));
        if (rows.length === 0) return null;
        const max = Math.max(...rows.map((r) => r.value), 0.0001);
        return (
          <div key={metric} className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-300">{metric}</h3>
            <div className="space-y-2">
              {rows.map((r) => (
                <div key={r.name} className="grid grid-cols-[140px_1fr_80px] items-center gap-3 text-sm">
                  <span className="text-slate-400">{r.name}</span>
                  <Bar value={r.value} max={max} />
                  <span className="text-right text-slate-300">{r.value.toFixed(3)}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
