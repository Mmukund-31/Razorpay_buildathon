interface StatTileProps {
  label: string;
  value: string;
  sublabel?: string;
}

export default function StatTile({ label, value, sublabel }: StatTileProps) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-100">{value}</p>
      {sublabel && <p className="mt-1 text-xs text-slate-500">{sublabel}</p>}
    </div>
  );
}

export function formatPaise(paise: number, currency = "INR"): string {
  const symbol = currency === "INR" ? "₹" : currency + " ";
  return `${symbol}${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}
