import { useEffect, useMemo, useReducer, useState } from "react";
import { ChevronDown } from "lucide-react";

import {
  formatDate,
  getDebateSequence,
  getOrderedHypotheses,
  getProbabilityFirstPortfolio,
} from "../domain";
import CrossExaminationRail from "./CrossExaminationRail";
import EvidenceField from "./EvidenceField";
import HypothesisRoster from "./HypothesisRoster";
import WalkForwardDock from "./WalkForwardDock";
import SwitchingBayesPanel from "./SwitchingBayesPanel";

function initialFlow(revealed) {
  return {
    phase: revealed ? "revealed" : "ready",
    cursor: revealed ? 59 : -1,
    playing: false,
    activeSlot: 1,
    error: "",
  };
}

function advance(state, total) {
  if (state.phase === "adjudicating" || state.phase === "revealed") {
    return state;
  }
  const cursor = Math.min(state.cursor + 1, total - 1);
  return {
    ...state,
    cursor,
    phase: cursor === total - 1 ? "adjudicating" : "debating",
    playing: state.playing && cursor !== total - 1,
  };
}

function reducer(state, action) {
  switch (action.type) {
    case "TOGGLE":
      if (state.phase === "revealed") return initialFlow(false);
      if (state.phase === "ready" || state.phase === "error") {
        return {
          ...state,
          phase: "debating",
          cursor: 0,
          playing: true,
          error: "",
        };
      }
      if (state.phase === "debating") {
        return { ...state, playing: !state.playing };
      }
      return state;
    case "STEP":
      return advance({ ...state, playing: false }, action.total);
    case "TICK":
      return advance(state, action.total);
    case "REVEALED":
      return { ...state, phase: "revealed", playing: false };
    case "ERROR":
      return {
        ...state,
        phase: "error",
        playing: false,
        error: action.error,
      };
    case "SELECT_TICKET":
      return { ...state, activeSlot: action.slot };
    default:
      return state;
  }
}

export default function MechanismObservatory({
  activeGame,
  decisionRevealed,
  gameData,
  onDecisionReveal,
  onGameChange,
  onOpenHistory,
  recentEvents,
  switchingBayes,
}) {
  const decision = gameData.next_decision;
  const hypotheses = useMemo(
    () => getOrderedHypotheses(gameData),
    [gameData],
  );
  const sequence = useMemo(
    () => getDebateSequence(decision),
    [decision],
  );
  const portfolio = useMemo(
    () => getProbabilityFirstPortfolio(decision, activeGame),
    [activeGame, decision],
  );
  const [flow, dispatch] = useReducer(
    reducer,
    decisionRevealed,
    initialFlow,
  );
  const [activeHypothesis, setActiveHypothesis] = useState(
    hypotheses.find((row) => row.code === "H1")?.id ??
      hypotheses[0]?.id,
  );
  const [filter, setFilter] = useState("all");
  const currentCritique =
    flow.cursor >= 0 ? sequence[flow.cursor] : null;

  useEffect(() => {
    if (!flow.playing) return undefined;
    const timer = window.setInterval(() => {
      dispatch({ type: "TICK", total: sequence.length });
    }, 170);
    return () => window.clearInterval(timer);
  }, [flow.playing, sequence.length]);

  useEffect(() => {
    if (flow.phase !== "adjudicating") return undefined;
    const timer = window.setTimeout(() => {
      onDecisionReveal(activeGame)
        .then(() => dispatch({ type: "REVEALED" }))
        .catch((error) =>
          dispatch({ type: "ERROR", error: error.message }),
        );
    }, 900);
    return () => window.clearTimeout(timer);
  }, [activeGame, flow.phase, onDecisionReveal]);

  const tickets =
    flow.phase === "revealed" ? portfolio.tickets : [];

  return (
    <div className="mechanism-observatory">
      <section className="observatory-command-bar">
        <div className="observatory-game-switch" aria-label="遊戲切換">
          {[
            ["super", "威力彩"],
            ["lotto649", "大樂透"],
          ].map(([id, label]) => (
            <button
              aria-pressed={activeGame === id}
              className={activeGame === id ? "is-active" : ""}
              key={id}
              type="button"
              onClick={() => onGameChange(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="observatory-target">
          <small>目標期別</small>
          <strong>第 {decision.target.period} 期</strong>
          <em>{formatDate(decision.target.date)}</em>
          <ChevronDown size={16} />
        </span>
        <div className="unknown-contract">
          <i />
          <span>
            <small>生成機制</small>
            <strong>UNKNOWN</strong>
          </span>
          <p>不預設隨機 · 不預設有規律</p>
        </div>
      </section>

      <SwitchingBayesPanel
        activeGame={activeGame}
        study={switchingBayes}
      />

      <div className="observatory-grid">
        <HypothesisRoster
          activeId={activeHypothesis}
          hypotheses={hypotheses}
          onSelect={setActiveHypothesis}
        />
        <EvidenceField
          activeHypothesis={activeHypothesis}
          activeSlot={flow.activeSlot}
          currentCritique={currentCritique}
          debateStep={Math.max(0, flow.cursor + 1)}
          decision={decision}
          error={flow.error}
          hypotheses={hypotheses}
          onSelectTicket={(slot) =>
            dispatch({ type: "SELECT_TICKET", slot })
          }
          phase={flow.phase}
          tickets={tickets}
          totalCritiques={sequence.length}
        />
        <CrossExaminationRail
          cursor={flow.cursor}
          decision={decision}
          filter={filter}
          isPlaying={flow.playing}
          onFilterChange={setFilter}
          onPlayToggle={() => dispatch({ type: "TOGGLE" })}
          onStep={() =>
            dispatch({ type: "STEP", total: sequence.length })
          }
          phase={flow.phase}
          sequence={sequence}
        />
      </div>

      <WalkForwardDock
        events={recentEvents}
        hypotheses={hypotheses}
        onOpenHistory={onOpenHistory}
      />
    </div>
  );
}
