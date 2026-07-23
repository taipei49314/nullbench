import { ChevronRight, Info } from "lucide-react";

import AgentGlyph from "./AgentGlyph";

function evidenceStatus(hypothesis) {
  if (hypothesis.id === "independent_null") return "比較基準";
  const [low, high] =
    hypothesis.blind_evidence?.confidence_interval_95 ?? [0, 0];
  if (low > 0) return "盲測領先";
  if (high < 0) return "盲測落後";
  return "證據未定";
}

function signed(value, digits = 2) {
  const numeric = Number(value ?? 0);
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(digits)}`;
}

export default function HypothesisRoster({
  activeId,
  hypotheses,
  onSelect,
}) {
  return (
    <aside className="hypothesis-roster">
      <header>
        <span>
          <strong>假說競技場</strong>
          <small>公開五強 · 無保留席位</small>
        </span>
        <Info aria-hidden="true" size={17} />
      </header>

      <div className="hypothesis-list">
        {hypotheses.map((hypothesis) => {
          const evidence = hypothesis.blind_evidence;
          const skill = Number(evidence?.mean_skill_vs_h0 ?? 0) * 1000;
          const interval = (
            evidence?.confidence_interval_95 ?? [0, 0]
          ).map((value) => Number(value) * 1000);
          return (
            <button
              aria-pressed={activeId === hypothesis.id}
              className={`hypothesis-row is-${hypothesis.color} ${
                activeId === hypothesis.id ? "is-active" : ""
              }`}
              key={hypothesis.id}
              type="button"
              onClick={() => onSelect(hypothesis.id)}
            >
              <span className="hypothesis-code">{hypothesis.code}</span>
              <span className="hypothesis-glyph">
                <AgentGlyph agentId={hypothesis.id} size={22} />
              </span>
              <span className="hypothesis-copy">
                <span>
                  <strong>{hypothesis.name}</strong>
                  <em>{evidenceStatus(hypothesis)}</em>
                </span>
                <small>{hypothesis.doctrine}</small>
                <b>{signed(skill)}</b>
                <i>
                  95% [{signed(interval[0])}, {signed(interval[1])}]
                </i>
              </span>
              <ChevronRight size={17} />
            </button>
          );
        })}
      </div>

      <footer>
        <span>分數：相對 H0 的逐期 Brier skill × 1000</span>
        <strong>只讀封存結果</strong>
      </footer>
    </aside>
  );
}
