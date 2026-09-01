import { useParams } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { formatPaise, formatPercent } from "../components/StatTile";
import { useApi } from "../hooks/useApi";
import type { DecisionTrace as DecisionTraceType } from "../api/types";

function humanizeReasonCode(code: string): string {
  return code
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-300">{title}</h3>
      {children}
    </div>
  );
}

export default function DecisionTrace() {
  const { caseId } = useParams();
  const { data, error, loading } = useApi<DecisionTraceType>(
    `/recovery-cases/${caseId}/decision-trace`,
    5000,
  );

  if (loading && !data) return <p className="text-slate-400">Loading…</p>;
  if (error) return <p className="text-rose-400">Failed to load decision trace: {error}</p>;
  if (!data) return null;

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Decision Trace — {data.recovery_case_id.slice(0, 8)}</h2>
        <StatusBadge status={data.status} />
      </div>

      <Section title="1. Why the payment failed">
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="text-slate-500">Amount</dt>
            <dd>{formatPaise(data.payment.amount, data.payment.currency)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Failure class</dt>
            <dd>{data.payment.failure_class ?? "unknown"}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-slate-500">Error reason</dt>
            <dd>{data.payment.error_reason ?? "—"}</dd>
          </div>
        </dl>
      </Section>

      <Section title="2. What the AI diagnosed">
        {data.ai_diagnosis ? (
          <div className="space-y-2 text-sm">
            <p>{data.ai_diagnosis.diagnosis}</p>
            <p className="text-slate-400">
              Confidence: {formatPercent(data.ai_diagnosis.confidence)} · Recommended:{" "}
              <span className="text-slate-200">{data.ai_diagnosis.recommended_action}</span> ·
              Mode: {data.ai_diagnosis.communication_mode}
            </p>
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            No valid AI diagnosis for this case (no LLM key configured, or the call failed —
            the pipeline fell back to the ML score alone; see docs/reliability.md).
          </p>
        )}
      </Section>

      <Section title="3. What actions were considered">
        {data.candidates.length === 0 ? (
          <p className="text-sm text-slate-500">No candidate actions were scored.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-slate-500">
                <th className="pb-2 font-normal">Action</th>
                <th className="pb-2 font-normal">P(recovery)</th>
                <th className="pb-2 font-normal">Expected value</th>
              </tr>
            </thead>
            <tbody>
              {data.candidates.map((c) => (
                <tr
                  key={c.action_type}
                  className={`border-t border-slate-800 ${
                    c.action_type === data.selected_action ? "bg-slate-800/50" : ""
                  }`}
                >
                  <td className="py-2">
                    {c.action_type}
                    {c.action_type === data.selected_action && (
                      <span className="ml-2 text-xs text-emerald-400">selected</span>
                    )}
                  </td>
                  <td className="py-2">{formatPercent(c.recovery_probability)}</td>
                  <td className="py-2">{formatPaise(c.expected_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="4. Why policy allowed or rejected it">
        {data.policy_decision ? (
          data.policy_decision.allowed ? (
            <div className="text-sm">
              <p className="text-emerald-400">Allowed (policy {data.policy_decision.policy_version})</p>
            </div>
          ) : (
            <div className="rounded border border-rose-900 bg-rose-950/40 p-3 text-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-rose-400">
                AI recommendation blocked
              </p>
              <p className="mt-1 text-slate-200">
                Action: <span className="font-mono">{data.selected_action ?? "—"}</span>
              </p>
              <p className="mt-1 text-slate-300">
                Reason:{" "}
                {data.policy_decision.reason_codes.length > 0
                  ? data.policy_decision.reason_codes.map(humanizeReasonCode).join(", ")
                  : "—"}
              </p>
              {(() => {
                const blockedCandidate = data.candidates.find(
                  (c) => c.action_type === data.selected_action,
                );
                return blockedCandidate ? (
                  <p className="mt-1 text-slate-400">
                    Potential unnecessary intervention:{" "}
                    <span className="text-slate-200">
                      {formatPaise(blockedCandidate.expected_recovery)}
                    </span>
                  </p>
                ) : null;
              })()}
              <p className="mt-1 text-xs text-slate-500">policy {data.policy_decision.policy_version}</p>
            </div>
          )
        ) : (
          <p className="text-sm text-slate-500">No policy evaluation yet.</p>
        )}
      </Section>

      <Section title="5. What happened afterward">
        {data.execution ? (
          <>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-slate-500">Channel</dt>
                <dd>{data.execution.channel ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Status</dt>
                <dd>{data.execution.status}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Consent recorded</dt>
                <dd>{data.execution.consent_recorded ? "Yes" : "No"}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-slate-500">Reference</dt>
                <dd className="break-all">{data.execution.external_reference ?? "—"}</dd>
              </div>
            </dl>
            {data.execution.channel === "voice" && data.execution.result?.transcript ? (
              <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
                <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">
                  Simulated call transcript
                </p>
                <pre className="whitespace-pre-wrap font-sans text-sm text-slate-300">
                  {String(data.execution.result.transcript)}
                </pre>
              </div>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-slate-500">No action executed yet.</p>
        )}
        {data.outcome && <p className="mt-2 text-sm text-slate-300">{data.outcome}</p>}
        {data.actual_recovered_amount != null && (
          <div className="mt-3 rounded border border-emerald-900 bg-emerald-950/30 p-3 text-sm">
            <p className="text-xs uppercase tracking-wide text-emerald-500">
              Actual recovered revenue
            </p>
            <p className="mt-1 text-lg font-semibold text-emerald-300">
              {formatPaise(data.actual_recovered_amount, data.payment.currency)}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Verified via a reconciled payment.captured/payment_link.paid webhook — distinct
              from the expected-value estimate above.
            </p>
          </div>
        )}
      </Section>
    </div>
  );
}
