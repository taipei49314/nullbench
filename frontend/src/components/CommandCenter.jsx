import { useEffect, useMemo, useReducer, useState } from "react";

import { getDebateSequence, getLatestReview } from "../domain";
import AgentCouncil from "./AgentCouncil";
import DebateRail from "./DebateRail";
import DecisionArena from "./DecisionArena";
import ReplayDock from "./ReplayDock";

const createInitialFlow = (revealed) => ({
  phase: revealed ? "revealed" : "ready",
  cursor: revealed ? 59 : -1,
  playing: false,
  selectedSlot: 1,
  error: "",
});

function advanceDebate(state, total) {
  if (state.phase === "adjudicating" || state.phase === "revealed") {
    return state;
  }
  const cursor = Math.min(state.cursor + 1, total - 1);
  return {
    ...state,
    cursor,
    phase: cursor === total - 1 ? "adjudicating" : "debating",
    playing: cursor !== total - 1 && state.playing,
  };
}

function flowReducer(state, action) {
  switch (action.type) {
    case "TOGGLE":
      if (state.phase === "revealed") return createInitialFlow(false);
      if (state.phase === "ready" || state.phase === "error") {
        return { ...state, phase: "debating", cursor: 0, playing: true };
      }
      if (state.phase === "debating") {
        return { ...state, playing: !state.playing };
      }
      return state;
    case "STEP":
      return advanceDebate({ ...state, playing: false }, action.total);
    case "TICK":
      return advanceDebate(state, action.total);
    case "REVEAL":
      return state.phase === "adjudicating"
        ? { ...state, phase: "revealed", playing: false }
        : state;
    case "REVEAL_ERROR":
      return {
        ...state,
        phase: "error",
        playing: false,
        error: action.error,
      };
    case "SELECT":
      return state.phase === "revealed"
        ? { ...state, selectedSlot: action.slot }
        : state;
    default:
      return state;
  }
}

export default function CommandCenter({
  activeGame,
  decisionRevealed,
  gameData,
  recentEvents,
  onGameChange,
  onInspectAgent,
  onOpenHistory,
  onDecisionReveal,
}) {
  const decision = gameData.next_decision;
  const debateSequence = useMemo(
    () => getDebateSequence(decision),
    [decision],
  );
  const [flow, dispatch] = useReducer(
    flowReducer,
    decisionRevealed,
    createInitialFlow,
  );
  const [debateFilter, setDebateFilter] = useState("all");
  const currentCritique =
    flow.cursor >= 0 ? debateSequence[flow.cursor] : null;
  const latestReview = useMemo(
    () => getLatestReview(recentEvents),
    [recentEvents],
  );
  const revealed = flow.phase === "revealed";
  const focusedTicket = revealed
    ? decision.selected_tickets[flow.selectedSlot - 1]
    : null;
  const activeAgent =
    focusedTicket?.source_agent ?? currentCritique?.critic ?? null;

  useEffect(() => {
    if (!flow.playing) return undefined;
    const timer = window.setInterval(() => {
      dispatch({ type: "TICK", total: debateSequence.length });
    }, 360);
    return () => window.clearInterval(timer);
  }, [flow.playing, debateSequence.length]);

  useEffect(() => {
    if (flow.phase !== "adjudicating") return undefined;
    const timer = window.setTimeout(() => {
      onDecisionReveal(activeGame).then(() => {
        dispatch({ type: "REVEAL" });
      }).catch((error) => {
        dispatch({ type: "REVEAL_ERROR", error: error.message });
      });
    }, 1450);
    return () => window.clearTimeout(timer);
  }, [activeGame, flow.phase, onDecisionReveal]);

  return (
    <div className="command-center">
      <div className="command-grid">
        <AgentCouncil
          activeAgent={activeAgent}
          gameData={gameData}
          locked={!revealed}
          onInspectAgent={onInspectAgent}
        />
        <DecisionArena
          activeGame={activeGame}
          activeSlot={revealed ? flow.selectedSlot : null}
          currentCritique={currentCritique}
          debateStep={Math.max(0, flow.cursor + 1)}
          error={flow.error}
          gameData={gameData}
          isPlaying={flow.playing}
          onGameChange={onGameChange}
          onPlayToggle={() => dispatch({ type: "TOGGLE" })}
          onSelectTicket={(slot) => dispatch({ type: "SELECT", slot })}
          onStep={() =>
            dispatch({ type: "STEP", total: debateSequence.length })
          }
          phase={flow.phase}
          selectedSlot={flow.selectedSlot}
          totalCritiques={debateSequence.length}
        />
        <DebateRail
          cursor={flow.cursor}
          decision={decision}
          filter={debateFilter}
          isPlaying={flow.playing}
          onFilterChange={setDebateFilter}
          onInspectAgent={revealed ? onInspectAgent : null}
          phase={flow.phase}
          sequence={debateSequence}
        />
      </div>
      <ReplayDock
        gameData={gameData}
        latestReview={latestReview}
        onOpenHistory={onOpenHistory}
      />
    </div>
  );
}
