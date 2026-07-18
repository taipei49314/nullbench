import {
  BrainCircuit,
  LockKeyhole,
  ScanLine,
  UsersRound,
} from "lucide-react";

import { AGENTS, getProposalMap } from "../domain";
import NumberBall from "./NumberBall";

const STANCE_LABELS = {
  support: "支持",
  neutral: "中立",
  oppose: "反對",
};

export default function DebateStage({
  currentCritique,
  debateStep,
  decision,
  error,
  phase,
  totalCritiques,
}) {
  if (phase === "error") {
    return (
      <section className="candidate-stage is-error">
        <LockKeyhole size={34} />
        <strong>裁決資料讀取失敗</strong>
        <p>{error}</p>
      </section>
    );
  }

  if (phase === "ready") {
    const agentCounts = Object.entries(
      decision.proposals.reduce((counts, proposal) => {
        counts[proposal.agent] = (counts[proposal.agent] ?? 0) + 1;
        return counts;
      }, {}),
    );
    return (
      <section className="candidate-stage is-ready">
        <div className="candidate-seal">
          <LockKeyhole size={32} />
          <span>
            <strong>15 組候選已封存</strong>
            <small>最終 5 注尚未裁決，也不會提前顯示</small>
          </span>
        </div>
        <div className="candidate-roster">
          {agentCounts.map(([agentId, count]) => (
            <span key={agentId}>
              <i>
                <UsersRound size={15} />
              </i>
              <strong>{AGENTS[agentId].name}</strong>
              <small>{count} 組提案</small>
            </span>
          ))}
        </div>
        <p>按下「開始辯論」，完成 60 次交叉評議後才會進入裁決。</p>
      </section>
    );
  }

  if (phase === "adjudicating") {
    return (
      <section className="candidate-stage is-adjudicating">
        <span className="adjudicating-orbit">
          <BrainCircuit size={43} />
        </span>
        <strong>60 次辯論完成</strong>
        <p>裁決器正在計算評議權重、號碼重疊與單一 Agent 集中懲罰。</p>
        <div className="adjudicating-scan">
          <i />
        </div>
      </section>
    );
  }

  if (!currentCritique) return null;
  const proposal = getProposalMap(decision).get(currentCritique.target);
  return (
    <section
      className={`candidate-stage is-debating stance-${currentCritique.stance}`}
      key={`${currentCritique.critic}-${currentCritique.target}`}
    >
      <header>
        <span>
          <ScanLine size={16} />
          目前受評候選 · 尚未裁決
        </span>
        <strong>
          {String(debateStep).padStart(2, "0")} / {totalCritiques}
        </strong>
      </header>
      <div className="candidate-exchange">
        <div>
          <small>評議 Agent</small>
          <strong>{AGENTS[currentCritique.critic].name}</strong>
        </div>
        <span>→</span>
        <div>
          <small>提案來源</small>
          <strong>{AGENTS[proposal.agent].name}</strong>
          <code>{proposal.proposal_id}</code>
        </div>
      </div>
      <div className="candidate-balls">
        {proposal.numbers.map((number) => (
          <NumberBall active key={number} number={number} />
        ))}
        {proposal.special !== null ? (
          <>
            <i />
            <NumberBall active number={proposal.special} special />
          </>
        ) : null}
      </div>
      <blockquote>{currentCritique.reason}</blockquote>
      <footer>
        <span>{STANCE_LABELS[currentCritique.stance]}</span>
        評議強度 {currentCritique.score.toFixed(2)}
      </footer>
    </section>
  );
}
