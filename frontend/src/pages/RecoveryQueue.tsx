import { useState } from "react";
import { Link } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { formatPaise } from "../components/StatTile";
import { useApi } from "../hooks/useApi";
import type { RecoveryCaseListResponse } from "../api/types";

const STATUS_FILTERS = [
  "",
  "DETECTED",
  "ELIGIBLE",
  "ANALYZING",
  "ACTION_PROPOSED",
  "POLICY_APPROVED",
  "SCHEDULED",
  "EXECUTING",
  "SUCCEEDED",
  "FAILED",
  "POLICY_REJECTED",
  "ABSTAINED",
  "EXPIRED",
  "ESCALATED",
];

export default function RecoveryQueue() {
  const [statusFilter, setStatusFilter] = useState("");
  const path = statusFilter
    ? `/recovery-cases?status_filter=${statusFilter}&page_size=50`
    : "/recovery-cases?page_size=50";
  const { data, error, loading } = useApi<RecoveryCaseListResponse>(path);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-400">Filter by status:</label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s || "All"}
            </option>
          ))}
        </select>
      </div>

      {loading && !data && <p className="text-slate-400">Loading…</p>}
      {error && <p className="text-rose-400">Failed to load queue: {error}</p>}
      {data && (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <p className="mb-3 text-xs text-slate-500">{data.total} case(s)</p>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-slate-500">
                <th className="pb-2 font-normal">Case</th>
                <th className="pb-2 font-normal">Payment</th>
                <th className="pb-2 font-normal">Amount</th>
                <th className="pb-2 font-normal">Status</th>
                <th className="pb-2 font-normal">Action</th>
                <th className="pb-2 font-normal">Attempts</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} className="border-t border-slate-800">
                  <td className="py-2">
                    <Link to={`/cases/${c.id}`} className="text-sky-400 hover:underline">
                      {c.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="py-2 text-slate-500">{c.payment_id.slice(0, 8)}</td>
                  <td className="py-2">{formatPaise(c.amount, c.currency)}</td>
                  <td className="py-2">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="py-2 text-slate-400">{c.selected_action ?? "—"}</td>
                  <td className="py-2 text-slate-400">
                    {c.attempt_count}
                  </td>
                </tr>
              ))}
              {data.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-slate-500">
                    No cases match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
