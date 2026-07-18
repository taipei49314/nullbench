import { useEffect, useMemo, useState } from "react";

import { getLatestReview } from "../domain";
import AgentCouncil from "./AgentCouncil";
import DebateRail from "./DebateRail";
import DecisionArena from "./DecisionArena";
import ReplayDock from "./ReplayDock";

export default function CommandCenter({
  activeGame,
  gameData,
  recentEvents,
  onGameChange,
  onInspectAgent,
  onOpenHistory,
}) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [debateFilter, setDebateFilter] = useState("all");
  const [selectedSlot, setSelectedSlot] = useState(1);
  const decision = gameData.next_decision;

  useEffect(() => {
    if (!isPlaying) return undefined;
    const timer = window.setInterval(() => {
      setCursor((value) => value + 1);
    }, 1150);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  const activeSlot = isPlaying
    ? (cursor % decision.selected_tickets.length) + 1
    : selectedSlot;
  const activeTicket = decision.selected_tickets[activeSlot - 1];
  const latestReview = useMemo(
    () => getLatestReview(recentEvents),
    [recentEvents],
  );

  return (
    <div className="command-center">
      <div className="command-grid">
        <AgentCouncil
          activeAgent={activeTicket.source_agent}
          gameData={gameData}
          onInspectAgent={onInspectAgent}
        />
        <DecisionArena
          activeGame={activeGame}
          activeSlot={activeSlot}
          debateStep={(cursor % decision.critiques.length) + 1}
          gameData={gameData}
          isPlaying={isPlaying}
          onGameChange={onGameChange}
          onPlayToggle={() => setIsPlaying((value) => !value)}
          onSelectTicket={(slot) => {
            setIsPlaying(false);
            setSelectedSlot(slot);
          }}
          onStep={() => setCursor((value) => value + 1)}
          selectedSlot={selectedSlot}
          totalCritiques={decision.critiques.length}
        />
        <DebateRail
          activeIndex={cursor}
          decision={decision}
          filter={debateFilter}
          onFilterChange={setDebateFilter}
          onInspectAgent={onInspectAgent}
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
