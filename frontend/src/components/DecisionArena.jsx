import {
  ChevronDown,
  Pause,
  Play,
  Radio,
  SkipForward,
} from "lucide-react";

import { AGENTS, formatDate } from "../domain";
import ArenaRadar from "./ArenaRadar";
import NumberBall from "./NumberBall";

export default function DecisionArena({
  activeGame,
  activeSlot,
  debateStep,
  gameData,
  isPlaying,
  onGameChange,
  onPlayToggle,
  onSelectTicket,
  onStep,
  selectedSlot,
  totalCritiques,
}) {
  const decision = gameData.next_decision;
  const focusedTicket = decision.selected_tickets[activeSlot - 1];
  const focusedRanking = decision.adjudication.ranking.find(
    (ranking) => ranking.proposal_id === focusedTicket.source_proposal,
  );
  const debateProgress = `${(debateStep / totalCritiques) * 100}%`;

  return (
    <section className="decision-arena">
      <ArenaRadar pulse={isPlaying} />
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
            type="button"
            onClick={onPlayToggle}
          >
            {isPlaying ? <Pause size={17} /> : <Play size={17} />}
            {isPlaying ? "暫停辯論" : "播放辯論"}
            <ChevronDown size={16} />
          </button>
          <button
            className="icon-control"
            type="button"
            onClick={onStep}
            aria-label="下一段評議"
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
        className={`playback-status ${isPlaying ? "is-live" : ""}`}
      >
        <span>
          <Radio size={15} />
          {isPlaying ? "議會正在辯論" : "議會待命"}
        </span>
        <i aria-hidden="true">
          <b style={{ "--progress": debateProgress }} />
        </i>
        <strong>
          評議 {String(debateStep).padStart(2, "0")} / {totalCritiques}
        </strong>
      </div>

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
    </section>
  );
}
