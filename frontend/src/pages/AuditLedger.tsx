import { useApi } from "../hooks/useApi";
import type { AuditLogEntry } from "../api/types";

export default function AuditLedger() {
  const { data, error, loading } = useApi<{ items: AuditLogEntry[]; total: number }>(
    "/audit?page_size=100",
    5000,
  );

  if (loading && !data) return <p className="text-slate-400">Loading…</p>;
  if (error) return <p className="text-rose-400">Failed to load audit ledger: {error}</p>;
  if (!data) return null;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <p className="mb-3 text-xs text-slate-500">
        {data.total} entries · append-only — see app/repositories/audit_log_repository.py
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="text-slate-500">
              <th className="pb-2 font-normal">Time</th>
              <th className="pb-2 font-normal">Entity</th>
              <th className="pb-2 font-normal">Event</th>
              <th className="pb-2 font-normal">Actor</th>
              <th className="pb-2 font-normal">Decision</th>
              <th className="pb-2 font-normal">Reason</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((entry) => (
              <tr key={entry.id} className="border-t border-slate-800 align-top">
                <td className="whitespace-nowrap py-2 text-slate-500">
                  {new Date(entry.created_at).toLocaleTimeString()}
                </td>
                <td className="py-2">
                  {entry.entity_type}:{entry.entity_id.slice(0, 8)}
                </td>
                <td className="py-2 text-slate-200">{entry.event}</td>
                <td className="py-2 text-slate-400">{entry.actor}</td>
                <td className="py-2 text-slate-400">{entry.decision ?? "—"}</td>
                <td className="py-2 text-slate-500">{entry.reason ?? "—"}</td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-slate-500">
                  No audit entries yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
