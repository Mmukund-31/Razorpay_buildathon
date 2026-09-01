import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiPost, ApiRequestError } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { formatPaise } from "../components/StatTile";
import { useApi } from "../hooks/useApi";
import type { RecoveryCaseDetail } from "../api/types";

export default function RecoveryCase() {
  const { caseId } = useParams();
  const { data, error, loading, refetch } = useApi<RecoveryCaseDetail>(
    `/recovery-cases/${caseId}`,
    4000,
  );
  const [consentRecorded, setConsentRecorded] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function runEvaluate() {
    setBusy(true);
    setActionError(null);
    try {
      await apiPost(`/recovery-cases/${caseId}/evaluate`, { consent_recorded: consentRecorded });
      refetch();
    } catch (err) {
      setActionError(err instanceof ApiRequestError ? err.message : "Evaluate failed");
    } finally {
      setBusy(false);
    }
  }

  async function runExecute() {
    setBusy(true);
    setActionError(null);
    try {
      await apiPost(`/recovery-cases/${caseId}/execute`, { consent_recorded: consentRecorded });
      refetch();
    } catch (err) {
      setActionError(err instanceof ApiRequestError ? err.message : "Execute failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <p className="text-slate-400">Loading…</p>;
  if (error) return <p className="text-rose-400">Failed to load case: {error}</p>;
  if (!data) return null;

  const needsConsent = data.selected_action === "HINGLISH_VOICE";

  return (
    <div className="max-w-3xl space-y-6">
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Case {data.id.slice(0, 8)}</h2>
          <StatusBadge status={data.status} />
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-slate-500">Amount</dt>
            <dd>{formatPaise(data.amount, data.currency)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Payment</dt>
            <dd>{data.payment_id.slice(0, 8)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Selected action</dt>
            <dd>{data.selected_action ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Attempts</dt>
            <dd>
              {data.attempt_count} / {data.max_attempts}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Recovery window expires</dt>
            <dd>
              {data.recovery_window_expires_at
                ? new Date(data.recovery_window_expires_at).toLocaleString()
                : "—"}
            </dd>
          </div>
        </dl>
        <Link
          to={`/cases/${data.id}/trace`}
          className="mt-4 inline-block text-sm text-sky-400 hover:underline"
        >
          View decision trace →
        </Link>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-6">
        <h3 className="mb-3 text-sm font-semibold text-slate-300">Manual controls</h3>
        <p className="mb-3 text-xs text-slate-500">
          The pipeline runs autonomously on real webhook/simulator events. These buttons
          re-enter the same idempotent evaluate/execute endpoints the pipeline itself calls —
          useful for demoing the Hinglish voice consent flow or retrying manually.
        </p>
        {needsConsent && (
          <label className="mb-3 flex items-center gap-2 text-sm text-amber-300">
            <input
              type="checkbox"
              checked={consentRecorded}
              onChange={(e) => setConsentRecorded(e.target.checked)}
            />
            Customer consented ("Haan, retry kar do.") — required before HINGLISH_VOICE can
            execute
          </label>
        )}
        <div className="flex gap-3">
          <button
            onClick={runEvaluate}
            disabled={busy}
            className="rounded bg-sky-700 px-3 py-1.5 text-sm text-white hover:bg-sky-600 disabled:opacity-50"
          >
            Evaluate
          </button>
          <button
            onClick={runExecute}
            disabled={busy}
            className="rounded bg-emerald-700 px-3 py-1.5 text-sm text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            Execute
          </button>
        </div>
        {actionError && <p className="mt-3 text-sm text-rose-400">{actionError}</p>}
      </div>
    </div>
  );
}
