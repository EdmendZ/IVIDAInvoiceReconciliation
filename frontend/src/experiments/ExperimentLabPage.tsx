import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import {
  canEnterGold,
  displayValue,
  formatCost,
  formatPercent,
} from "./experimentPresentation";
import type {
  EvaluationRun,
  ExperimentDefinition,
  FeedbackCandidate,
  FeedbackClassification,
  PromotionDecision,
} from "./experimentTypes";

const CLASSIFICATIONS: FeedbackClassification[] = [
  "model_error",
  "acceptable_variant",
  "reviewer_correction_error",
  "business_context_update",
];

function RunSelector({
  label,
  runs,
  value,
  onChange,
}: {
  label: string;
  runs: EvaluationRun[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select a completed run</option>
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {run.run_id}
          </option>
        ))}
      </select>
    </label>
  );
}

function RunEvidence({ run }: { run: EvaluationRun | undefined }) {
  if (!run?.summary) return <p className="muted">Select a completed run.</p>;
  return (
    <>
      <dl className="lab-metrics">
        <div><dt>Documents</dt><dd>{run.summary.document_count}</dd></div>
        <div><dt>Schema valid</dt><dd>{formatPercent(run.summary.schema_valid_rate)}</dd></div>
        <div><dt>Field accuracy</dt><dd>{formatPercent(run.summary.field_micro_accuracy)}</dd></div>
        <div><dt>Line-item F1</dt><dd>{formatPercent(run.summary.line_item_f1)}</dd></div>
        <div><dt>Evidence</dt><dd>{formatPercent(run.summary.evidence_coverage)}</dd></div>
        <div><dt>Average cost</dt><dd>{formatCost(run.summary.average_cost_aud)}</dd></div>
      </dl>
      <div className="table-scroll">
        <table className="result-table">
          <thead><tr><th>Slice</th><th>Documents</th><th>Errors</th></tr></thead>
          <tbody>
            {run.slices.map((slice) => (
              <tr key={`${slice.dimension}:${slice.value}`}>
                <td>{slice.dimension}: {slice.value}</td>
                <td>{slice.document_count}</td><td>{slice.error_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DecisionSummary({ decision }: { decision: PromotionDecision | null }) {
  if (!decision) return null;
  return (
    <section className="lab-panel" aria-label="Promotion decision">
      <div className="lab-panel-heading">
        <div><span className="eyebrow">FAIL-CLOSED DECISION</span><h3>{decision.outcome}</h3></div>
      </div>
      <div className="table-scroll"><table className="result-table">
        <thead><tr><th>Gate</th><th>Result</th><th>Baseline</th><th>Candidate</th><th>Threshold</th><th>Reason</th></tr></thead>
        <tbody>{decision.checks.map((check) => <tr key={check.code}>
          <td>{check.code}{check.hard_gate ? " (hard)" : ""}</td>
          <td>{check.passed ? "Pass" : "Fail"}</td>
          <td>{displayValue(check.baseline_value)}</td><td>{displayValue(check.candidate_value)}</td>
          <td>{displayValue(check.threshold)}</td><td>{check.reason}</td>
        </tr>)}</tbody>
      </table></div>
    </section>
  );
}

function FeedbackQueue({
  items,
  refresh,
}: {
  items: FeedbackCandidate[];
  refresh: () => Promise<unknown>;
}) {
  const [classifications, setClassifications] = useState<Record<string, FeedbackClassification>>({});
  const [gold, setGold] = useState<Record<string, boolean>>({});
  async function confirm(item: FeedbackCandidate) {
    const classification = classifications[item.candidate_id];
    if (!classification) return;
    await api(`/api/feedback-candidates/${encodeURIComponent(item.candidate_id)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ classification, include_in_gold: Boolean(gold[item.candidate_id]) }),
    });
    await refresh();
  }
  return <section className="lab-panel"><div className="lab-panel-heading"><div>
    <span className="eyebrow">HUMAN FEEDBACK</span><h3>Feedback candidates</h3>
  </div></div><div className="lab-feedback-list">{items.map((item) => {
    const classification = classifications[item.candidate_id] ?? item.classification;
    return <article key={item.candidate_id} className="lab-feedback-card">
      <div><strong>{item.field_path}</strong><small>{item.document_type} · {item.normalizer_model}</small>
        <p>{displayValue(item.old_value)} → {displayValue(item.new_value)}</p></div>
      <label>Classification<select value={classification ?? ""} onChange={(event) => {
        const next = event.target.value as FeedbackClassification;
        setClassifications((current) => ({ ...current, [item.candidate_id]: next }));
        if (!canEnterGold(next)) setGold((current) => ({ ...current, [item.candidate_id]: false }));
      }}><option value="">Select</option>{CLASSIFICATIONS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="lab-checkbox"><input type="checkbox" disabled={!canEnterGold(classification)} checked={Boolean(gold[item.candidate_id])} onChange={(event) => setGold((current) => ({ ...current, [item.candidate_id]: event.target.checked }))} /> Include in Gold</label>
      <button disabled={!classification} onClick={() => void confirm(item)}>Confirm</button>
    </article>;
  })}</div></section>;
}

export function ExperimentLabPage() {
  const definitions = useQuery({ queryKey: ["experiments"], queryFn: () => api<ExperimentDefinition[]>("/api/experiments") });
  const runs = useQuery({ queryKey: ["experiment-runs"], queryFn: () => api<EvaluationRun[]>("/api/experiment-runs") });
  const feedback = useQuery({ queryKey: ["feedback-candidates"], queryFn: () => api<FeedbackCandidate[]>("/api/feedback-candidates?confirmed=false") });
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [decision, setDecision] = useState<PromotionDecision | null>(null);
  const completed = (runs.data ?? []).filter((run) => run.status === "completed" && run.summary);
  const baselineRuns = useMemo(() => completed.filter((run) => definitions.data?.find((item) => item.experiment_id === run.experiment_id)?.role === "baseline"), [completed, definitions.data]);
  const candidateRuns = useMemo(() => completed.filter((run) => definitions.data?.find((item) => item.experiment_id === run.experiment_id)?.role === "candidate"), [completed, definitions.data]);
  const baseline = completed.find((run) => run.run_id === baselineId);
  const candidate = completed.find((run) => run.run_id === candidateId);
  async function compare() { setDecision(await api<PromotionDecision>("/api/promotion-decisions", { method: "POST", body: JSON.stringify({ baseline_run_id: baselineId, candidate_run_id: candidateId }) })); }
  if (definitions.isLoading || runs.isLoading || feedback.isLoading) return <div className="loading">Loading quality evidence…</div>;
  if (definitions.isError || runs.isError || feedback.isError) return <div className="page"><p className="error-banner">Quality Lab data could not be loaded.</p></div>;
  return <div className="page experiment-lab"><div className="page-heading"><div><span className="eyebrow">EXTRACTION QUALITY LAB</span><h2>Model evidence, not a model switch</h2><p>Compare immutable runs. Decisions never change production configuration automatically.</p></div></div>
    <section className="lab-panel"><div className="lab-selectors"><RunSelector label="Baseline" runs={baselineRuns} value={baselineId} onChange={setBaselineId} /><RunSelector label="Candidate" runs={candidateRuns} value={candidateId} onChange={setCandidateId} /><button className="primary" disabled={!baseline || !candidate} onClick={() => void compare()}>Compare completed runs</button></div>
      <div className="lab-run-grid"><div><h3>Baseline evidence</h3><RunEvidence run={baseline} /></div><div><h3>Candidate evidence</h3><RunEvidence run={candidate} /></div></div></section>
    <DecisionSummary decision={decision} />
    <FeedbackQueue items={feedback.data ?? []} refresh={() => feedback.refetch()} />
  </div>;
}
