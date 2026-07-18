import { Radio, SlidersHorizontal } from "lucide-react";

import { AGENTS, getProposalMap } from "../domain";
import AgentGlyph from "./AgentGlyph";

const FILTERS = [
  ["all", "全部"],
  ["support", "支持"],
  ["neutral", "中立"],
  ["oppose", "反對"],
];

const STANCE_LABELS = {
  support: "支持",
  neutral: "中立",
  oppose: "反對",
};

const WINDOW_SIZE = 5;

function interleaveCritiques(critiques) {
  const byCritic = new Map();
  for (const critique of critiques) {
    const group = byCritic.get(critique.critic) ?? [];
    group.push(critique);
    byCritic.set(critique.critic, group);
  }
  const groups = [...byCritic.values()];
  const result = [];
  const maxLength = Math.max(...groups.map((group) => group.length));
  for (let index = 0; index < maxLength; index += 1) {
    for (const group of groups) {
      if (group[index]) result.push(group[index]);
    }
  }
  return result;
}

export default function DebateRail({
  activeIndex,
  decision,
  filter,
  onFilterChange,
  onInspectAgent,
}) {
  const proposals = getProposalMap(decision);
  const interleaved = interleaveCritiques(decision.critiques);
  const visible =
    filter === "all"
      ? interleaved
      : interleaved.filter((critique) => critique.stance === filter);
  const start =
    visible.length > WINDOW_SIZE
      ? activeIndex % (visible.length - WINDOW_SIZE + 1)
      : 0;
  const windowed = visible.slice(start, start + WINDOW_SIZE);

  return (
    <aside className="debate-rail">
      <div className="debate-title">
        <span>即時交叉評議</span>
        <b>
          <Radio size={13} /> LIVE
        </b>
      </div>
      <div className="debate-filters">
        {FILTERS.map(([id, label]) => (
          <button
            className={filter === id ? "is-active" : ""}
            key={id}
            type="button"
            onClick={() => onFilterChange(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div aria-live="polite" className="debate-stream">
        {windowed.map((critique, index) => {
          const target = proposals.get(critique.target);
          return (
            <button
              className={`debate-entry stance-${critique.stance} ${
                index === 0 ? "is-current" : ""
              }`}
              key={`${critique.critic}-${critique.target}`}
              type="button"
              onClick={() => onInspectAgent(critique.critic)}
            >
              <time>10:24:{String(31 - index * 3).padStart(2, "0")}</time>
              <span className="debate-avatar">
                <AgentGlyph agentId={critique.critic} size={17} />
              </span>
              <span className="debate-body">
                <strong>{AGENTS[critique.critic].name}</strong>
                <em>{STANCE_LABELS[critique.stance]}</em>
                <small>
                  → {AGENTS[target.agent].name} · {target.proposal_id}
                </small>
                <p>{critique.reason}</p>
              </span>
            </button>
          );
        })}
      </div>
      <div className="debate-footer">
        <SlidersHorizontal size={14} />
        正在顯示 {start + 1}–
        {Math.min(start + WINDOW_SIZE, visible.length)} /{" "}
        {visible.length} 筆
      </div>
    </aside>
  );
}
