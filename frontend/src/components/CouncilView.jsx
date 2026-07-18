import { ArrowUpRight } from "lucide-react";

import { getOrderedAgents } from "../domain";
import AgentGlyph from "./AgentGlyph";

export default function CouncilView({ gameData, onInspectAgent }) {
  const agents = getOrderedAgents(gameData);
  return (
    <div className="workspace-view council-view">
      <header className="workspace-heading">
        <div>
          <h1>Agent 議會</h1>
          <p>可信度只由揭曉後的逐期回饋更新；當期結果不會倒灌當期決策。</p>
        </div>
        <div className="workspace-kpi">
          <span>已檢討</span>
          <strong>{gameData.final_state.draws_reviewed.toLocaleString()}</strong>
          <small>輪</small>
        </div>
      </header>
      <div className="council-table">
        <div className="council-table-head">
          <span>順位</span>
          <span>Agent / 方法</span>
          <span>可信度</span>
          <span>累計最佳主號命中</span>
          <span>檢討數</span>
          <span />
        </div>
        {agents.map((agent, index) => (
          <button
            key={agent.id}
            type="button"
            onClick={() => onInspectAgent(agent.id)}
          >
            <span className="council-rank">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="council-agent">
              <i>
                <AgentGlyph agentId={agent.id} size={27} />
              </i>
              <span>
                <strong>{agent.name}</strong>
                <small>{agent.doctrine}</small>
              </span>
            </span>
            <span className="council-rating-cell">
              <b>{agent.rating.toFixed(8)}</b>
              <i style={{ "--rating": `${(agent.rating / 1.5) * 100}%` }} />
            </span>
            <strong>
              {agent.cumulative_best_main_hits.toLocaleString()}
            </strong>
            <span>{agent.reviews.toLocaleString()}</span>
            <ArrowUpRight size={19} />
          </button>
        ))}
      </div>
      <div className="council-method">
        <strong>更新紀律</strong>
        <p>
          五位 Agent 每期各提出三組候選。揭曉後以各自最佳提案的命中點數做相對更新，
          評分限制在 0.50–1.50；這是模擬內部權重，不是開出機率。
        </p>
      </div>
    </div>
  );
}
