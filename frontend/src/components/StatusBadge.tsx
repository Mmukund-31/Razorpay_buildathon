const STATUS_COLORS: Record<string, string> = {
  SUCCEEDED: "bg-emerald-900 text-emerald-300 border-emerald-700",
  POLICY_APPROVED: "bg-sky-900 text-sky-300 border-sky-700",
  EXECUTING: "bg-sky-900 text-sky-300 border-sky-700",
  SCHEDULED: "bg-amber-900 text-amber-300 border-amber-700",
  ACTION_PROPOSED: "bg-amber-900 text-amber-300 border-amber-700",
  ANALYZING: "bg-amber-900 text-amber-300 border-amber-700",
  ELIGIBLE: "bg-slate-800 text-slate-300 border-slate-600",
  DETECTED: "bg-slate-800 text-slate-300 border-slate-600",
  POLICY_REJECTED: "bg-rose-950 text-rose-300 border-rose-800",
  FAILED: "bg-rose-950 text-rose-300 border-rose-800",
  EXPIRED: "bg-slate-800 text-slate-500 border-slate-700",
  ABSTAINED: "bg-slate-800 text-slate-500 border-slate-700",
  ESCALATED: "bg-orange-950 text-orange-300 border-orange-800",
};

export default function StatusBadge({ status }: { status: string }) {
  const classes = STATUS_COLORS[status] ?? "bg-slate-800 text-slate-300 border-slate-600";
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${classes}`}>
      {status}
    </span>
  );
}
