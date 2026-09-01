interface PagePlaceholderProps {
  title: string;
  phase: string;
  description: string;
}

/** Every Phase 1 page renders this instead of hard-coded fake data — a page with hard-coded
 * numbers would violate the "no fake demo" rule as much as a fabricated API response would.
 * Real pages replace this component call in Phase 14, backed by the real endpoints these
 * placeholders name. */
export default function PagePlaceholder({ title, phase, description }: PagePlaceholderProps) {
  return (
    <div className="max-w-2xl rounded-lg border border-slate-800 bg-slate-900 p-6">
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-slate-400">{description}</p>
      <p className="mt-4 text-xs uppercase tracking-wide text-amber-500">Implemented in {phase}</p>
    </div>
  );
}
