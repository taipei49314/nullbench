import { useState } from "react";
import { ChevronRight, GitCompareArrows } from "lucide-react";

import { formatDate } from "../domain";
import NumberBall from "./NumberBall";

export default function HistoryView({ events, gameData }) {
  const [selectedSequence, setSelectedSequence] = useState(
    events.at(-1)?.sequence ?? null,
  );
  const selected =
    events.find((event) => event.sequence === selectedSequence) ?? events.at(-1);
  const ordered = [...events].reverse();
  const error = selected?.review.error_analysis;

  return (
    <div className="workspace-view history-view">
      <header className="workspace-heading">
        <div>
          <h1>歷史回放</h1>
          <p>
            每一期的決策、揭曉與檢討都由雜湊鏈連接；此處顯示最近{" "}
            {events.length} 期。
          </p>
        </div>
        <div className="workspace-kpi">
          <span>完整回放</span>
          <strong>{gameData.draws_replayed.toLocaleString()}</strong>
          <small>期</small>
        </div>
      </header>

      <div className="history-layout">
        <div className="history-list">
          <div className="history-list-head">
            <span>期別</span>
            <span>實際號碼</span>
            <span>最佳</span>
            <span>遺憾</span>
          </div>
          {ordered.map((event) => {
            const review = event.review;
            const active = event.sequence === selectedSequence;
            return (
              <button
                className={active ? "is-active" : ""}
                key={event.sequence}
                type="button"
                onClick={() => setSelectedSequence(event.sequence)}
              >
                <span>
                  <strong>{review.target.period}</strong>
                  <small>{formatDate(review.target.date)}</small>
                </span>
                <span className="history-balls">
                  {review.actual.numbers.map((number) => (
                    <NumberBall compact key={number} number={number} />
                  ))}
                </span>
                <b>{review.error_analysis.best_selected_main_hits}/6</b>
                <em>
                  {review.error_analysis.hindsight_selection_regret.toFixed(2)}
                </em>
                <ChevronRight size={17} />
              </button>
            );
          })}
        </div>

        {selected ? (
          <aside className="history-detail">
            <div className="history-detail-title">
              <GitCompareArrows size={22} />
              <span>
                <strong>第 {selected.review.target.period} 期檢討</strong>
                <small>{selected.review.error_analysis.interpretation}</small>
              </span>
            </div>
            <div className="history-score">
              <div>
                <span>最佳主號命中</span>
                <strong>{error.best_selected_main_hits}/6</strong>
              </div>
              <div>
                <span>未覆蓋實際號碼</span>
                <strong className="is-coral">
                  {error.missed_actual_numbers.join(" ") || "無"}
                </strong>
              </div>
              <div>
                <span>事後選擇遺憾</span>
                <strong className="is-coral">
                  {error.hindsight_selection_regret.toFixed(2)}
                </strong>
              </div>
            </div>
            <div className="selected-results">
              <h3>五注結果</h3>
              {selected.review.selected_results.map((result) => (
                <div key={result.slot}>
                  <span>第 {result.slot} 注</span>
                  <b>{result.main_hits}/6</b>
                  <em>{result.tier ?? "未達獎級"}</em>
                </div>
              ))}
            </div>
            <div className="review-hashes">
              <span>DECISION</span>
              <code>{selected.decision.decision_hash}</code>
              <span>REVIEW</span>
              <code>{selected.review.review_hash}</code>
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
