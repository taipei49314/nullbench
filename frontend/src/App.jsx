import { useCallback, useEffect, useState } from "react";

import { loadDashboard, revealDecision, syncLatest } from "./api";
import { hasRevealedDecision } from "./domain";
import AgentInspector from "./components/AgentInspector";
import AppHeader from "./components/AppHeader";
import CommandCenter from "./components/CommandCenter";
import CouncilView from "./components/CouncilView";
import HistoryView from "./components/HistoryView";
import LoadingScreen from "./components/LoadingScreen";
import ResearchView from "./components/ResearchView";
import VerificationView from "./components/VerificationView";

export default function App() {
  const [dashboard, setDashboard] = useState(null);
  const [error, setError] = useState("");
  const [syncState, setSyncState] = useState({
    status: "idle",
    phase: "starting",
    message: "準備檢查台彩官方資料",
  });
  const [activeGame, setActiveGame] = useState("super");
  const [activeView, setActiveView] = useState("decision");
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [revealedGames, setRevealedGames] = useState({});

  const handleDecisionReveal = useCallback(async (game) => {
    const decision = await revealDecision(game);
    setDashboard((current) => ({
      ...current,
      manifest: {
        ...current.manifest,
        games: {
          ...current.manifest.games,
          [game]: {
            ...current.manifest.games[game],
            next_decision: decision,
          },
        },
      },
    }));
    setRevealedGames((current) => ({ ...current, [game]: true }));
  }, []);

  useEffect(() => {
    let live = true;
    const refresh = async (initial = false) => {
      let syncWarning = "";
      try {
        const syncResult = await syncLatest((state) => {
          if (live) setSyncState(state);
        });
        if (syncResult?.regenerated && live) {
          setRevealedGames({});
        }
      } catch (reason) {
        syncWarning = reason.message;
        if (live) {
          setSyncState({
            status: "error",
            phase: "error",
            message: "官方同步失敗，改用本地已驗證快取",
            error: reason.message,
          });
        }
      }

      try {
        const payload = await loadDashboard();
        if (live) {
          setDashboard({ ...payload, syncWarning });
          setError("");
        }
      } catch (reason) {
        if (live && initial) setError(reason.message);
      }
    };

    refresh(true);
    const timer = window.setInterval(() => refresh(false), 5 * 60 * 1000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!dashboard) {
    return <LoadingScreen error={error} syncState={syncState} />;
  }

  const gameData = dashboard.manifest.games[activeGame];
  const recentEvents = dashboard.recent[activeGame];
  const decisionRevealed = hasRevealedDecision(
    revealedGames[activeGame],
    gameData.next_decision,
  );
  let activeContent;
  if (activeView === "history") {
    activeContent = <HistoryView gameData={gameData} events={recentEvents} />;
  } else if (activeView === "council") {
    activeContent = (
      <CouncilView gameData={gameData} onInspectAgent={setSelectedAgent} />
    );
  } else if (activeView === "verification") {
    activeContent = (
      <VerificationView
        gameData={gameData}
        manifest={dashboard.manifest}
      />
    );
  } else if (activeView === "research") {
    activeContent = (
      <ResearchView
        activeGame={activeGame}
        key={activeGame}
        onGameChange={setActiveGame}
        study={dashboard.research.councilQuality}
      />
    );
  } else {
    activeContent = (
      <CommandCenter
        activeGame={activeGame}
        decisionRevealed={decisionRevealed}
        gameData={gameData}
        key={`${activeGame}:${gameData.next_decision.target.period}`}
        recentEvents={recentEvents}
        onGameChange={setActiveGame}
        onInspectAgent={setSelectedAgent}
        onOpenHistory={() => setActiveView("history")}
        onDecisionReveal={handleDecisionReveal}
      />
    );
  }

  return (
    <div className="app-shell">
      <AppHeader
        activeView={activeView}
        gameData={gameData}
        onNavigate={setActiveView}
      />
      <main className="app-stage">{activeContent}</main>
      {selectedAgent ? (
        <AgentInspector
          agentId={selectedAgent}
          decisionRevealed={decisionRevealed}
          gameData={gameData}
          onChangeAgent={setSelectedAgent}
          onClose={() => setSelectedAgent(null)}
        />
      ) : null}
      {dashboard.syncWarning ? (
        <div className="sync-warning" role="status">
          官方同步失敗，目前顯示本地已驗證快取：{dashboard.syncWarning}
        </div>
      ) : null}
    </div>
  );
}
