import { Link } from "react-router-dom";
import StatTile, { formatPaise, formatPercent } from "../components/StatTile";
import StatusBadge from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import type { DashboardMetrics } from "../api/types";

export default function CommandCenter() {
  const { data, error, loading } = useApi<DashboardMetrics>("/dashboard");

  if (loading && !data) return <p className="text-slate-400">Loading…</p>;
  if (error) return <p className="text-rose-400">Failed to load dashboard: {error}</p>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Revenue at Risk" value={formatPaise(data.total_amount_at_risk)} />
        <StatTile label="Recoverable Revenue" value={formatPaise(data.total_recoverable)} />
        <StatTile label="Recovered Revenue" value={formatPaise(data.total_recovered)} />
        <StatTile label="Recovery Rate" value={formatPercent(data.recovery_rate)} />
        <StatTile label="Active Cases" value={String(data.active_cases_count)} />
        <StatTile label="Actions Executed" value={String(data.actions_executed_count)} />
        <StatTile
          label="Actions Prevented"
          value={String(data.actions_prevented_count)}
          sublabel="blocked by policy"
        />
        <StatTile label="Abstentions" value={String(data.abstentions_count)} />
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-300">Recent Cases</h2>
        {data.recent_cases.length === 0 ? (
          <p className="text-sm text-slate-500">
            No cases yet — generate a failure storm from the Simulation page to see the
            pipeline run end to end.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-slate-500">
                <th className="pb-2 font-normal">Case</th>
                <th className="pb-2 font-normal">Amount</th>
                <th className="pb-2 font-normal">Status</th>
                <th className="pb-2 font-normal">Selected Action</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_cases.map((c) => (
                <tr key={c.id} className="border-t border-slate-800">
                  <td className="py-2">
                    <Link to={`/cases/${c.id}`} className="text-sky-400 hover:underline">
                      {c.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="py-2">{formatPaise(c.amount, c.currency)}</td>
                  <td className="py-2">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="py-2 text-slate-400">{c.selected_action ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
