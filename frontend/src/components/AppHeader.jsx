import { useEffect, useRef, useState } from "react";
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
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef(null);
  const decision = gameData.next_decision;

  useEffect(
    () => () => {
      window.clearTimeout(copyTimer.current);
    },
    [],
  );

  const copyHash = () => {
    navigator.clipboard?.writeText(decision.decision_hash);
    setCopied(true);
    window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopied(false), 1400);
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
          {decision.critique_count ?? decision.critiques.length} 次交叉評議
        </span>
        <span>
          <Database size={15} />
          {gameData.draws_replayed.toLocaleString()} 期已回放
        </span>
        <span>
          <CheckCircle2 size={15} />
          完整測試鏈
        </span>
      </div>

      <button className="hash-lockup" type="button" onClick={copyHash}>
        <span>{copied ? "已複製完整雜湊" : "決策鏈"}</span>
        <code>
          {copied
            ? "COPIED"
            : `${decision.decision_hash.slice(0, 8)}…${decision.decision_hash.slice(-8)}`}
        </code>
        <Copy size={14} />
      </button>
    </header>
  );
}
