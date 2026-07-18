import { useState } from "react";
import { ChevronLeft, ChevronRight, Focus, X } from "lucide-react";

import {
  AGENTS,
  formatNumbers,
  getAgentSeries,
  getOrderedAgents,
  getProposalMap,
  getRankingMap,
} from "../domain";
import AgentGlyph from "./AgentGlyph";
import NumberBall from "./NumberBall";
import SignalChart from "./SignalChart";

const STANCE_LABELS = {
  support: "支持",
  neutral: "中立",
  oppose: "反對",
};

export default function AgentInspector({
  agentId,
  gameData,
  onChangeAgent,
  onClose,
}) {
  const [focused, setFocused] = useState(false);
  const decision = gameData.next_decision;
  const orderedAgents = getOrderedAgents(gameData);
  const currentIndex = orderedAgents.findIndex((agent) => agent.id === agentId);
  const agent = orderedAgents[currentIndex];
  const proposals = decision.proposals.filter(
    (proposal) => proposal.agent === agentId,
  );
  const proposalMap = getProposalMap(decision);
  const rankingMap = getRankingMap(decision);
  const proposalIds = new Set(proposals.map((proposal) => proposal.proposal_id));
  const critiques = decision.critiques
    .filter((critique) => proposalIds.has(critique.target))
    .slice(0, 5);
  const series = getAgentSeries(agentId, proposals, agent.rating);
  const leadingRanking = proposals.reduce((best, proposal) => {
    const ranking = rankingMap.get(proposal.proposal_id);
    if (!ranking) return best;
    return !best || ranking.final_score > best.final_score ? ranking : best;
  }, null);

  const moveAgent = (direction) => {
    const next =
      (currentIndex + direction + orderedAgents.length) % orderedAgents.length;
    onChangeAgent(orderedAgents[next].id);
  };

  return (
    <div className="inspector-backdrop" onMouseDown={onClose}>
      <aside
        aria-label={`${agent.name} 本期論證`}
        className={`agent-inspector ${focused ? "is-focused" : ""}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="inspector-header">
          <div>
            <span className="inspector-agent-icon">
              <AgentGlyph agentId={agentId} size={23} />
            </span>
            <h2>{agent.name} · 本期論證</h2>
            <p>
              評分 <strong>{agent.rating.toFixed(4)}</strong>
            </p>
          </div>
          <div className="inspector-actions">
            <button
              type="button"
              onClick={() => moveAgent(-1)}
              aria-label="上一位 Agent"
            >
              <ChevronLeft size={17} /> 上一位
            </button>
            <button
              type="button"
              onClick={() => moveAgent(1)}
              aria-label="下一位 Agent"
            >
              下一位 <ChevronRight size={17} />
            </button>
            <button
              className={focused ? "is-active" : ""}
              type="button"
              onClick={() => setFocused((value) => !value)}
            >
              <Focus size={16} />
              {focused ? "已聚焦" : "聚焦此 Agent"}
            </button>
            <button
              className="inspector-close"
              type="button"
              onClick={onClose}
              aria-label="關閉 Agent 詳情"
            >
              <X size={23} />
            </button>
          </div>
        </header>

        <section className="inspector-section">
          <div className="inspector-section-title">
            <strong>三組提案</strong>
            <span>{decision.target.date} · {decision.target.period}</span>
          </div>
          <div className="proposal-list">
            {proposals.map((proposal, index) => {
              const ranking = rankingMap.get(proposal.proposal_id);
              return (
                <div
                  className={`proposal-row ${ranking ? "is-selected" : ""}`}
                  key={proposal.proposal_id}
                >
                  <span className="proposal-index">{index + 1}</span>
                  <span className="proposal-balls">
                    {proposal.numbers.map((number) => (
                      <NumberBall
                        active={Boolean(ranking)}
                        compact
                        key={number}
                        number={number}
                      />
                    ))}
                  </span>
                  <span className="proposal-outcome">
                    {ranking ? (
                      <>
                        <b>入選第 {ranking.rank} 注</b>
                        <code>{ranking.final_score.toFixed(8)}</code>
                      </>
                    ) : (
                      <>
                        <small>未入選</small>
                        <code>{formatNumbers(proposal.numbers).join(" ")}</code>
                      </>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="inspector-section evidence-section">
          <div className="inspector-section-title">
            <strong>歷史證據</strong>
            <span>近 30 期 · 決策前快照</span>
          </div>
          <SignalChart series={series} />
          <p className="evidence-note">
            數值只反映此 Agent 對歷史訊號的相對排序；不把歷史相關描述成開獎因果。
          </p>
        </section>

        <section className="inspector-section">
          <div className="inspector-section-title">
            <strong>交叉評議</strong>
            <span>{critiques.length} / 12 筆聚焦顯示</span>
          </div>
          <div className="critique-table">
            <div className="critique-head">
              <span>評議者</span>
              <span>立場</span>
              <span>強度</span>
              <span>意見摘要</span>
            </div>
            {critiques.map((critique) => {
              const target = proposalMap.get(critique.target);
              return (
                <div
                  className={`critique-row stance-${critique.stance}`}
                  key={`${critique.critic}-${critique.target}`}
                >
                  <span>{AGENTS[critique.critic].name}</span>
                  <b>{STANCE_LABELS[critique.stance]}</b>
                  <span className="strength-bar">
                    <i style={{ "--strength": `${critique.score * 100}%` }} />
                    {critique.score.toFixed(2)}
                  </span>
                  <p>
                    {critique.reason}
                    <small>→ {target.proposal_id}</small>
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        <section className="adjudication-equation">
          <div>
            <strong>裁決算式</strong>
            <span>基礎分 × 評議權重 − 重疊懲罰 − 同 Agent 集中</span>
          </div>
          <code>
            {leadingRanking?.final_score.toFixed(8) ?? "未入選"}
          </code>
        </section>
      </aside>
    </div>
  );
}
