import {
  BrainCircuit,
  LockKeyhole,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
} from "lucide-react";

import { AGENTS, getProposalMap } from "../domain";

const FILTERS = [
  ["all", "全部"],
  ["support", "支持"],
  ["oppose", "反對"],
  ["neutral", "不確定"],
];

const STANCE = {
  support: "支持",
  oppose: "反對",
  neutral: "不確定",
};

export default function CrossExaminationRail({
  cursor,
  decision,
  filter,
  isPlaying,
  onFilterChange,
  onPlayToggle,
  onStep,
  phase,
  sequence,
}) {
  const proposalMap = getProposalMap(decision);
  const available =
    phase === "revealed" ? sequence : sequence.slice(0, cursor + 1);
  const filtered =
    filter === "all"
      ? available
      : available.filter((critique) => critique.stance === filter);
  const visible = filtered.slice(-7);
  const judge = decision.adjudication?.judge;

  return (
    <aside className="cross-examination-rail">
      <header>
        <span>
          <strong>
            {phase === "revealed" ? "終局裁決理由" : "交叉詰問直播"}
          </strong>
          <small>每個假說評議其餘 12 組提案</small>
        </span>
        <b>
          {String(
            phase === "revealed" ? sequence.length : Math.max(0, cursor + 1),
          ).padStart(2, "0")}
          <i>/60</i>
        </b>
      </header>

      <div className="cross-filters">
        {FILTERS.map(([id, label]) => (
          <button
            aria-pressed={filter === id}
            className={filter === id ? "is-active" : ""}
            key={id}
            type="button"
            onClick={() => onFilterChange(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {phase === "revealed" && judge ? (
        <div className="judge-rationale">
          <span>
            <BrainCircuit size={24} />
            <strong>{judge.model ?? "可重現規則裁判"}</strong>
          </span>
          <p>{judge.summary}</p>
          <dl>
            <div>
              <dt>來源</dt>
              <dd>{judge.source}</dd>
            </div>
            <div>
              <dt>假說權利</dt>
              <dd>完全對等</dd>
            </div>
            <div>
              <dt>決策雜湊</dt>
              <dd>{decision.decision_hash.slice(0, 12)}…</dd>
            </div>
          </dl>
        </div>
      ) : visible.length > 0 ? (
        <div aria-live="polite" className="cross-stream">
          {visible.map((critique, index) => {
            const target = proposalMap.get(critique.target);
            return (
              <article
                className={`stance-${critique.stance} ${
                  index === visible.length - 1 ? "is-current" : ""
                }`}
                key={`${critique.critic}:${critique.target}`}
              >
                <time>
                  {String(
                    available.indexOf(critique) + 1,
                  ).padStart(2, "0")}
                </time>
                <em>{STANCE[critique.stance]}</em>
                <span>
                  <strong>
                    {AGENTS[critique.critic]?.code} →{" "}
                    {AGENTS[target?.agent]?.code}
                  </strong>
                  <small>{critique.target}</small>
                  <p>{critique.reason}</p>
                </span>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="cross-empty">
          <LockKeyhole size={31} />
          <strong>詰問尚未開始</strong>
          <span>未來評議不會提前顯示</span>
        </div>
      )}

      <div className="cross-controls">
        <button
          className="cross-primary"
          disabled={phase === "adjudicating"}
          type="button"
          onClick={onPlayToggle}
        >
          {phase === "revealed" ? (
            <RotateCcw size={18} />
          ) : isPlaying ? (
            <Pause size={18} />
          ) : (
            <Play size={18} />
          )}
          {phase === "ready"
            ? "啟動假說辯論"
            : phase === "revealed"
              ? "重新播放辯論"
              : isPlaying
                ? "暫停"
                : "繼續"}
        </button>
        <button
          aria-label="單步執行下一次交叉評議"
          disabled={phase === "adjudicating" || phase === "revealed"}
          type="button"
          onClick={onStep}
        >
          <SkipForward size={18} />
          單步
        </button>
      </div>
    </aside>
  );
}
