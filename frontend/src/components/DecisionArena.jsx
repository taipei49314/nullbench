import { ChevronDown, Pause, Play, SkipForward } from "lucide-react";

import { AGENTS, formatDate } from "../domain";
import ArenaRadar from "./ArenaRadar";
import NumberBall from "./NumberBall";

export default function DecisionArena({
  activeGame,
  activeSlot,
  gameData,
  isPlaying,
  onGameChange,
  onPlayToggle,
  onSelectTicket,
  onStep,
  selectedSlot,
}) {
  const decision = gameData.next_decision;
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
            className="primary-control"
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

      <div className="ticket-stack" aria-label="裁決出的五注號碼">
        {decision.selected_tickets.map((ticket) => {
          const active = ticket.slot === activeSlot;
          const selected = ticket.slot === selectedSlot;
          return (
            <button
              className={`ticket-row ${active ? "is-live" : ""} ${
                selected ? "is-selected" : ""
              }`}
              key={ticket.slot}
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

      <div className="decision-footnote">
        <span>{decision.adjudication.method}</span>
        <code>{decision.decision_hash.slice(0, 20)}</code>
      </div>
    </section>
  );
}
