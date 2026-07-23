import {
  BrainCircuit,
  LockKeyhole,
  Radio,
  ScanLine,
} from "lucide-react";

import { AGENTS, formatNumbers, getProposalMap } from "../domain";
import NumberBall from "./NumberBall";

function HypothesisPaths({ activeId, hypotheses, pulse }) {
  return (
    <div className={`hypothesis-paths ${pulse ? "is-pulsing" : ""}`}>
      <svg
        aria-label="五個假說匯入封存裁決閘門"
        preserveAspectRatio="none"
        role="img"
        viewBox="0 0 720 286"
      >
        {hypotheses.map((hypothesis, index) => {
          const startY = 34 + index * 53;
          const controlY = 143 + (index - 2) * 12;
          return (
            <g
              className={
                activeId === hypothesis.id ? "is-active" : ""
              }
              key={hypothesis.id}
            >
              <path
                d={`M 58 ${startY} C 230 ${startY - 20}, 380 ${controlY}, 596 143`}
              />
              <circle cx="58" cy={startY} r="5" />
              <circle
                className="evidence-pulse"
                cx={210 + index * 43}
                cy={startY + (controlY - startY) * 0.45}
                r="4"
                style={{ "--delay": `${index * -0.32}s` }}
              />
              <text x="14" y={startY + 5}>
                {hypothesis.code}
              </text>
            </g>
          );
        })}
        <circle className="aperture-ring" cx="625" cy="143" r="47" />
        <circle className="aperture-core" cx="625" cy="143" r="30" />
      </svg>
      <span className="aperture-lock">
        <LockKeyhole size={23} />
      </span>
      <span className="aperture-label">
        <strong>決策閘門</strong>
        <small>完成評議後開啟</small>
      </span>
    </div>
  );
}

function TicketContribution({ decision, hypothesis, ticket }) {
  const snapshot = (decision.hypotheses ?? []).find(
    (row) => row.id === hypothesis.id,
  );
  if (!snapshot) return null;
  const mean =
    ticket.numbers.reduce(
      (total, number) =>
        total + Number(snapshot.main_probabilities[number - 1] ?? 0),
      0,
    ) / ticket.numbers.length;
  const uniform = 6 / snapshot.main_probabilities.length;
  const ratio = Math.max(0.2, Math.min(1.8, mean / uniform));
  return (
    <span title={`${hypothesis.code} 相對均勻 ${ratio.toFixed(2)} 倍`}>
      <i style={{ "--contribution": `${(ratio / 1.8) * 100}%` }} />
      <small>{hypothesis.code}</small>
    </span>
  );
}

function PortfolioDeck({
  activeSlot,
  decision,
  hypotheses,
  onSelectTicket,
  tickets,
}) {
  const selected = tickets.find((ticket) => ticket.slot === activeSlot);
  return (
    <div className="portfolio-deck">
      <header>
        <span>
          <strong>候選號碼組合</strong>
          <small>模型建議集 · 純模擬</small>
        </span>
        <b>{tickets.length} 組已封存</b>
      </header>
      <div className="observatory-ticket-list">
        {tickets.map((ticket) => (
          <button
            aria-pressed={ticket.slot === activeSlot}
            className={ticket.slot === activeSlot ? "is-active" : ""}
            key={ticket.slot}
            type="button"
            onClick={() => onSelectTicket(ticket.slot)}
          >
            <span className="observatory-ticket-slot">{ticket.slot}</span>
            <span className="observatory-ticket-balls">
              {ticket.numbers.map((number) => (
                <NumberBall
                  active={ticket.slot === activeSlot}
                  key={number}
                  number={number}
                />
              ))}
              {ticket.special !== null ? (
                <>
                  <i />
                  <NumberBall
                    active={ticket.slot === activeSlot}
                    number={ticket.special}
                    special
                  />
                </>
              ) : null}
            </span>
            <span className="ticket-contributions">
              {hypotheses.map((hypothesis) => (
                <TicketContribution
                  decision={decision}
                  hypothesis={hypothesis}
                  key={hypothesis.id}
                  ticket={ticket}
                />
              ))}
            </span>
            <strong>
              {Number(ticket.debate_support ?? 0).toFixed(4)}
            </strong>
          </button>
        ))}
      </div>
      {selected ? (
        <div className="portfolio-readout">
          <span>
            <small>目前聚焦</small>
            <strong>組合 {String(activeSlot).padStart(2, "0")}</strong>
          </span>
          <code>{formatNumbers(selected.numbers).join(" · ")}</code>
          <p>
            五個假說的號碼邊際機率共同形成此組合；色條表示各假說相對自身均勻
            基準的支持程度，不是中獎保證。
          </p>
        </div>
      ) : null}
    </div>
  );
}

export default function EvidenceField({
  activeHypothesis,
  activeSlot,
  currentCritique,
  debateStep,
  decision,
  error,
  hypotheses,
  onSelectTicket,
  phase,
  tickets,
  totalCritiques,
}) {
  const selectedHypothesis =
    hypotheses.find((row) => row.id === activeHypothesis) ??
    hypotheses[0];
  const proposal = currentCritique
    ? getProposalMap(decision).get(currentCritique.target)
    : null;
  const revealed = phase === "revealed" && tickets.length === 5;

  return (
    <section className="evidence-field">
      <header>
        <span>
          <strong>證據場域</strong>
          <small>假說軌跡與封存流動</small>
        </span>
        <b className={phase === "debating" ? "is-live" : ""}>
          <Radio size={13} />
          {phase === "ready"
            ? "READY"
            : phase === "debating"
              ? "LIVE"
              : phase === "adjudicating"
                ? "JUDGING"
                : phase === "revealed"
                  ? "SEALED"
                  : "ERROR"}
        </b>
      </header>

      {revealed ? (
        <PortfolioDeck
          activeSlot={activeSlot}
          decision={decision}
          hypotheses={hypotheses}
          onSelectTicket={onSelectTicket}
          tickets={tickets}
        />
      ) : (
        <>
          <HypothesisPaths
            activeId={activeHypothesis}
            hypotheses={hypotheses}
            pulse={phase === "debating" || phase === "adjudicating"}
          />
          <div className={`current-thesis is-${phase}`}>
            {phase === "error" ? (
              <>
                <LockKeyhole size={26} />
                <span>
                  <small>裁決資料讀取失敗</small>
                  <strong>{error}</strong>
                </span>
              </>
            ) : phase === "adjudicating" ? (
              <>
                <BrainCircuit size={29} />
                <span>
                  <small>終局裁判正在核對輸出</small>
                  <strong>qwen3:8b 正在比較五個未知機制假說</strong>
                </span>
                <i className="adjudication-loader" />
              </>
            ) : currentCritique && proposal ? (
              <>
                <ScanLine size={25} />
                <span>
                  <small>
                    評議 {String(debateStep).padStart(2, "0")} /{" "}
                    {totalCritiques} · {AGENTS[currentCritique.critic]?.code}
                    {" → "}
                    {AGENTS[proposal.agent]?.code}
                  </small>
                  <strong>{currentCritique.reason}</strong>
                </span>
              </>
            ) : (
              <>
                <AgentGlyphProxy id={selectedHypothesis.id} />
                <span>
                  <small>目前主張 · {selectedHypothesis.code}</small>
                  <strong>{selectedHypothesis.thesis}</strong>
                </span>
              </>
            )}
          </div>
          <div className="sealed-candidate-note">
            <LockKeyhole size={18} />
            <span>
              <strong>15 組提案已封存</strong>
              <small>完成 60 次交叉評議前，不顯示最後五組號碼</small>
            </span>
          </div>
        </>
      )}
    </section>
  );
}

function AgentGlyphProxy({ id }) {
  const label = AGENTS[id]?.code ?? "H?";
  return <span className="thesis-code">{label}</span>;
}
