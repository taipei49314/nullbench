import { GripVertical } from "lucide-react";

import { getOrderedAgents } from "../domain";
import AgentGlyph from "./AgentGlyph";

export default function AgentCouncil({
  activeAgent,
  gameData,
  locked = false,
  onInspectAgent,
}) {
  const agents = getOrderedAgents(gameData);
  return (
    <aside className="agent-council">
      <div className="section-caption">
        <span>AGENT 議會</span>
        <b>[5/5]</b>
      </div>
      <div className="agent-stack">
        {agents.map((agent, index) => (
          <button
            className={`agent-row ${
              activeAgent === agent.id ? "is-active" : ""
            }`}
            disabled={locked}
            key={agent.id}
            type="button"
            onClick={() => onInspectAgent(agent.id)}
          >
            <span className="agent-index">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="agent-icon">
              <AgentGlyph agentId={agent.id} size={25} />
            </span>
            <span className="agent-copy">
              <strong>{agent.name}</strong>
              <small>{agent.doctrine}</small>
              <span className="agent-rating">
                評分 <b>{agent.rating.toFixed(4)}</b>
                <i style={{ "--rating": `${(agent.rating / 1.5) * 100}%` }} />
              </span>
            </span>
          </button>
        ))}
      </div>
      <p className="council-hint">
        <GripVertical size={14} />
        {locked
          ? "辯論完成後開放完整論證"
          : "點選 Agent 檢視本期完整論證"}
      </p>
    </aside>
  );
}
