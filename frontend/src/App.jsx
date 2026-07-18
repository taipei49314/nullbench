import { useEffect, useState } from "react";

import { loadDashboard } from "./api";
import AgentInspector from "./components/AgentInspector";
import AppHeader from "./components/AppHeader";
import CommandCenter from "./components/CommandCenter";
import CouncilView from "./components/CouncilView";
import HistoryView from "./components/HistoryView";
import LoadingScreen from "./components/LoadingScreen";
import VerificationView from "./components/VerificationView";

export default function App() {
  const [dashboard, setDashboard] = useState(null);
  const [error, setError] = useState("");
  const [activeGame, setActiveGame] = useState("super");
  const [activeView, setActiveView] = useState("decision");
  const [selectedAgent, setSelectedAgent] = useState(null);

  useEffect(() => {
    let live = true;
    loadDashboard()
      .then((payload) => {
        if (live) setDashboard(payload);
      })
      .catch((reason) => {
        if (live) setError(reason.message);
      });
    return () => {
      live = false;
    };
  }, []);

  if (!dashboard) {
    return <LoadingScreen error={error} />;
  }

  const gameData = dashboard.manifest.games[activeGame];
  const recentEvents = dashboard.recent[activeGame];
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
  } else {
    activeContent = (
      <CommandCenter
        activeGame={activeGame}
        gameData={gameData}
        key={activeGame}
        recentEvents={recentEvents}
        onGameChange={setActiveGame}
        onInspectAgent={setSelectedAgent}
        onOpenHistory={() => setActiveView("history")}
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
          gameData={gameData}
          onChangeAgent={setSelectedAgent}
          onClose={() => setSelectedAgent(null)}
        />
      ) : null}
      <div className="desktop-guard" role="alert">
        <strong>LOTTO//LAB 桌機戰情室</strong>
        <span>請將瀏覽器視窗拉寬至至少 1180px。</span>
      </div>
    </div>
  );
}
