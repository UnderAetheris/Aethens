import type { EvalSummaryOut, KnowledgeOut, LearningStateOut } from "../api/client";

interface IndicatorsProps {
  summary: EvalSummaryOut | null;
  knowledge: KnowledgeOut[];
  learning: LearningStateOut | null;
}

export function Indicators({ summary, knowledge, learning }: IndicatorsProps) {
  return (
    <div className="indicators">
      <h2>Indicators</h2>
      <p>Eval: {summary ? `${summary.passed}/${summary.total}` : "—"}</p>
      <p>Knowledge: {knowledge.length}</p>
      <p>Learning rules: {learning?.steps.length ?? 0}</p>
    </div>
  );
}
