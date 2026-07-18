import { LockKeyhole, Radio, SlidersHorizontal } from "lucide-react";

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

export default function DebateRail({
  cursor,
  decision,
  filter,
  isPlaying,
  onFilterChange,
  onInspectAgent,
  phase,
  sequence,
}) {
  const proposals = getProposalMap(decision);
  const revealed =
    phase === "revealed" ? sequence : sequence.slice(0, cursor + 1);
  const visible =
    filter === "all"
      ? revealed
      : revealed.filter((critique) => critique.stance === filter);
  const start = Math.max(0, visible.length - WINDOW_SIZE);
  const windowed = visible.slice(start, start + WINDOW_SIZE);

  return (
    <aside className="debate-rail">
      <div className="debate-title">
        <span>即時交叉評議</span>
        <b className={isPlaying ? "is-live" : ""}>
          <Radio size={13} />{" "}
          {isPlaying
            ? "LIVE"
            : phase === "ready"
              ? "LOCKED"
              : phase === "revealed"
                ? "COMPLETE"
                : "PAUSED"}
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
      {windowed.length > 0 ? (
        <div aria-live="polite" className="debate-stream">
          {windowed.map((critique, index) => {
            const target = proposals.get(critique.target);
            const current = index === windowed.length - 1;
            return (
              <button
                className={`debate-entry stance-${critique.stance} ${
                  current ? "is-current" : ""
                }`}
                disabled={!onInspectAgent}
                key={`${critique.critic}-${critique.target}`}
                type="button"
                onClick={() => onInspectAgent?.(critique.critic)}
              >
                <time>
                  {String(start + index + 1).padStart(2, "0")}/
                  {sequence.length}
                </time>
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
      ) : (
        <div className="debate-empty">
          <LockKeyhole size={25} />
          <strong>評議尚未開始</strong>
          <span>未來評論不會提前顯示</span>
        </div>
      )}
      <div className="debate-footer">
        <SlidersHorizontal size={14} />
        已揭露 {revealed.length} / {sequence.length} 筆
      </div>
    </aside>
  );
}
