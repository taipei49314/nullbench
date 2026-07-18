import {
  ArrowLeftRight,
  CheckCircle2,
  Copy,
  Database,
  Grid2X2,
} from "lucide-react";

import { NAV_ITEMS } from "../domain";

export default function AppHeader({
  activeView,
  gameData,
  onNavigate,
}) {
  const decision = gameData.next_decision;
  const copyHash = () => {
    navigator.clipboard?.writeText(decision.decision_hash);
  };

  return (
    <header className="app-header">
      <button
        className="brand-lockup"
        type="button"
        onClick={() => onNavigate("decision")}
        aria-label="回到即時裁決"
      >
        <span>LOTTO</span>
        <i>//</i>
        <span>LAB</span>
      </button>

      <nav className="primary-nav" aria-label="主要功能">
        {NAV_ITEMS.map((item) => (
          <button
            className={activeView === item.id ? "is-active" : ""}
            key={item.id}
            type="button"
            onClick={() => onNavigate(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="header-metrics" aria-label="模擬狀態">
        <span>
          <Grid2X2 size={15} />
          {decision.proposals.length} 組提案
        </span>
        <span>
          <ArrowLeftRight size={15} />
          {decision.critiques.length} 次交叉評議
        </span>
        <span>
          <Database size={15} />
          {gameData.draws_replayed.toLocaleString()} 期已回放
        </span>
        <span>
          <CheckCircle2 size={15} />
          129 項測試通過
        </span>
      </div>

      <button className="hash-lockup" type="button" onClick={copyHash}>
        <span>決策鏈</span>
        <code>
          {decision.decision_hash.slice(0, 8)}…
          {decision.decision_hash.slice(-8)}
        </code>
        <Copy size={14} />
      </button>
    </header>
  );
}
