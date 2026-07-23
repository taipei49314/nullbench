import {
  BrainCircuit,
  ChevronDown,
  CircleAlert,
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
  probabilityPortfolio,
  selectedSlot,
  totalCritiques,
}) {
  const decision = gameData.next_decision;
  const judge = decision.adjudication.judge;
  const qwenAccepted = judge?.source === "ollama";
  const probabilityFirst = !probabilityPortfolio.fallback_to_qwen;
  const displayedTickets = probabilityPortfolio.tickets;
  const revealRequested = phase === "revealed";
  const focusedTicket = revealRequested
    ? displayedTickets[activeSlot - 1]
    : null;
  const revealed =
    revealRequested &&
    displayedTickets.length === 5 &&
    Boolean(focusedTicket);
  const renderPhase = revealRequested && !revealed ? "error" : phase;
  const focusedRanking = focusedTicket
    ? decision.adjudication.ranking.find(
        (ranking) => ranking.proposal_id === focusedTicket.source_proposal,
      )
    : null;
  const debateProgress =
    renderPhase === "revealed" || renderPhase === "adjudicating"
      ? "100%"
      : `${(debateStep / totalCritiques) * 100}%`;
  const controlLabel =
    renderPhase === "ready"
      ? "開始辯論"
      : renderPhase === "revealed"
        ? "重新播放"
        : renderPhase === "error"
          ? "重新嘗試"
        : isPlaying
          ? "暫停辯論"
          : "繼續辯論";
  const statusLabel =
    renderPhase === "ready"
      ? "等待辯論開始"
      : renderPhase === "error"
        ? "裁決讀取失敗"
      : renderPhase === "adjudicating"
        ? "Qwen3:8b 終局裁決中"
        : renderPhase === "revealed"
          ? qwenAccepted
            ? probabilityFirst
              ? "Qwen3:8b 裁決 + 機率約束完成"
              : "Qwen3:8b 裁決完成"
            : "規則降級裁決完成"
          : isPlaying
            ? "議會正在辯論"
            : "辯論已暫停";

  return (
    <section className="decision-arena">
      <ArenaRadar pulse={isPlaying || renderPhase === "adjudicating"} />
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
            disabled={renderPhase === "adjudicating"}
            type="button"
            onClick={onPlayToggle}
          >
            {renderPhase === "revealed" ? (
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
            disabled={renderPhase === "adjudicating" || revealed}
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
          isPlaying || renderPhase === "adjudicating" ? "is-live" : ""
        } is-${renderPhase}`}
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
          <section
            className={`final-judge-strip ${
              qwenAccepted ? "is-qwen" : "is-fallback"
            }`}
          >
            <i>
              {qwenAccepted ? (
                <BrainCircuit size={24} />
              ) : (
                <CircleAlert size={24} />
              )}
            </i>
            <span>
              <small>
                {probabilityFirst ? "終局裁判 + 結構約束" : "終局裁判"}
              </small>
              <strong>
                {qwenAccepted
                  ? probabilityFirst
                    ? `${judge.model} → Coverage`
                    : judge.model
                  : "可重現規則降級"}
              </strong>
            </span>
            <p>
              {judge.summary}
              {probabilityFirst
                ? " 最終五注已套用30個互斥主號的全域最優機率結構。"
                : ""}
            </p>
          </section>
          <div
            className="ticket-stack"
            aria-label={
              probabilityFirst
                ? "機率最優的五注號碼"
                : "裁決出的五注號碼"
            }
          >
            {displayedTickets.map((ticket) => {
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
                    {probabilityFirst
                      ? "機率最優"
                      : AGENTS[ticket.source_agent]?.name ??
                        ticket.source_agent}
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
            <strong>
              {probabilityFirst
                ? "Coverage 約束"
                : AGENTS[focusedTicket.source_agent]?.name ??
                  focusedTicket.source_agent}
            </strong>
            <small>{focusedTicket.source_proposal}</small>
            <b>
              {probabilityFirst
                ? `辯論支持 ${focusedTicket.debate_support.toFixed(8)}`
                : `裁決分數 ${
                    focusedRanking?.final_score.toFixed(8) ?? "—"
                  }`}
            </b>
            <code>{decision.decision_hash.slice(0, 16)}</code>
            <em>
              {probabilityFirst
                ? probabilityPortfolio.construction
                : focusedRanking?.judge_reason ||
                  "模型輸出未通過驗證，本注沿用規則裁決。"}
            </em>
          </div>
        </>
      ) : (
          <DebateStage
            currentCritique={currentCritique}
            debateStep={debateStep}
            decision={decision}
            error={error}
            phase={renderPhase}
            totalCritiques={totalCritiques}
          />
      )}
    </section>
  );
}
