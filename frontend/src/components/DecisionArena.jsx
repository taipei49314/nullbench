import {
  ChevronDown,
  Pause,
  Play,
  Radio,
  RefreshCw,
  SkipForward,
} from "lucide-react";

import { AGENTS, formatDate } from "../domain";
import ArenaRadar from "./ArenaRadar";
import DebateStage from "./DebateStage";
import NumberBall from "./NumberBall";

export default function DecisionArena({
  activeGame,
  activeSlot,
  currentCritique,
  debateStep,
  error,
  gameData,
  isPlaying,
  onGameChange,
  onPlayToggle,
  onSelectTicket,
  onStep,
  phase,
  selectedSlot,
  totalCritiques,
}) {
  const decision = gameData.next_decision;
  const revealed = phase === "revealed";
  const focusedTicket = revealed
    ? decision.selected_tickets[activeSlot - 1]
    : null;
  const focusedRanking = focusedTicket
    ? decision.adjudication.ranking.find(
        (ranking) => ranking.proposal_id === focusedTicket.source_proposal,
      )
    : null;
  const debateProgress =
    phase === "revealed" || phase === "adjudicating"
      ? "100%"
      : `${(debateStep / totalCritiques) * 100}%`;
  const controlLabel =
    phase === "ready"
      ? "開始辯論"
      : phase === "revealed"
        ? "重新播放"
        : phase === "error"
          ? "重新嘗試"
        : isPlaying
          ? "暫停辯論"
          : "繼續辯論";
  const statusLabel =
    phase === "ready"
      ? "等待辯論開始"
      : phase === "error"
        ? "裁決讀取失敗"
      : phase === "adjudicating"
        ? "裁決器計算中"
        : phase === "revealed"
          ? "裁決完成"
          : isPlaying
            ? "議會正在辯論"
            : "辯論已暫停";

  return (
    <section className="decision-arena">
      <ArenaRadar pulse={isPlaying || phase === "adjudicating"} />
      <div className="decision-toolbar">
        <div className="game-switch" aria-label="遊戲切換">
          {[
            ["super", "威力彩"],
            ["lotto649", "大樂透"],
          ].map(([id, label]) => (
            <button
              className={activeGame === id ? "is-active" : ""}
              key={id}
              type="button"
              onClick={() => onGameChange(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="debate-controls">
          <button
            aria-pressed={isPlaying}
            className={`primary-control ${isPlaying ? "is-playing" : ""}`}
            disabled={phase === "adjudicating"}
            type="button"
            onClick={onPlayToggle}
          >
            {phase === "revealed" ? (
              <RefreshCw size={17} />
            ) : isPlaying ? (
              <Pause size={17} />
            ) : (
              <Play size={17} />
            )}
            {controlLabel}
            <ChevronDown size={16} />
          </button>
          <button
            aria-label="下一段評議"
            className="icon-control"
            disabled={phase === "adjudicating" || revealed}
            type="button"
            onClick={onStep}
          >
            <SkipForward size={17} />
          </button>
        </div>
      </div>

      <div className="decision-heading">
        <h1>下一期裁決</h1>
        <p>
          {formatDate(decision.target.date)}
          <span>·</span>第 {decision.target.period} 期
        </p>
      </div>

      <div
        aria-live="polite"
        className={`playback-status ${
          isPlaying || phase === "adjudicating" ? "is-live" : ""
        } is-${phase}`}
      >
        <span>
          <Radio size={15} />
          {statusLabel}
        </span>
        <i aria-hidden="true">
          <b style={{ "--progress": debateProgress }} />
        </i>
        <strong>
          評議 {String(debateStep).padStart(2, "0")} / {totalCritiques}
        </strong>
      </div>

      {revealed ? (
        <>
          <div className="ticket-stack" aria-label="裁決出的五注號碼">
            {decision.selected_tickets.map((ticket) => {
              const active = ticket.slot === activeSlot;
              const selected = ticket.slot === selectedSlot;
              return (
                <button
                  aria-pressed={selected}
                  className={`ticket-row ${active ? "is-live" : ""} ${
                    selected ? "is-selected" : ""
                  }`}
                  key={ticket.slot}
                  style={{ "--row": ticket.slot }}
                  type="button"
                  onClick={() => onSelectTicket(ticket.slot)}
                >
                  <span className="ticket-slot">{ticket.slot}</span>
                  <span className="ticket-agent">
                    {AGENTS[ticket.source_agent].name}
                  </span>
                  <span className="ticket-numbers">
                    {ticket.numbers.map((number) => (
                      <NumberBall
                        active={active || selected}
                        key={number}
                        number={number}
                      />
                    ))}
                  </span>
                  {ticket.special !== null ? (
                    <>
                      <span className="ticket-divider" />
                      <NumberBall
                        active={active}
                        number={ticket.special}
                        special
                      />
                    </>
                  ) : null}
                  <span className="ticket-signal" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                </button>
              );
            })}
          </div>

          <div className="ticket-readout" key={activeSlot}>
            <span>FOCUS {String(activeSlot).padStart(2, "0")}</span>
            <strong>{AGENTS[focusedTicket.source_agent].name}</strong>
            <small>{focusedTicket.source_proposal}</small>
            <b>裁決分數 {focusedRanking?.final_score.toFixed(8) ?? "—"}</b>
            <code>{decision.decision_hash.slice(0, 16)}</code>
          </div>
        </>
      ) : (
          <DebateStage
            currentCritique={currentCritique}
            debateStep={debateStep}
            decision={decision}
            error={error}
          phase={phase}
          totalCritiques={totalCritiques}
        />
      )}
    </section>
  );
}
