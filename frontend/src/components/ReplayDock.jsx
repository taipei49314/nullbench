import { ArrowRight, ScanSearch } from "lucide-react";

import { formatDate } from "../domain";

const YEARS = [2008, 2011, 2014, 2017, 2020, 2023, 2026];

export default function ReplayDock({
  gameData,
  latestReview,
  onOpenHistory,
}) {
  const error = latestReview?.error_analysis;
  const target = latestReview?.target;
  return (
    <section className="replay-dock">
      <div className="timeline-band">
        <div className="timeline-label">
          <strong>歷史回放時間軸</strong>
          <span>{gameData.draws_replayed.toLocaleString()} 期</span>
        </div>
        <div className="timeline-track">
          <div className="timeline-years">
            {YEARS.map((year) => (
              <span key={year}>{year}</span>
            ))}
          </div>
          <div className="timeline-wave">
            {Array.from({ length: 96 }, (_, index) => (
              <i
                key={index}
                style={{
                  "--height": `${12 + ((index * 17 + index ** 2) % 36)}%`,
                }}
              />
            ))}
          </div>
          <input
            aria-label="歷史回放位置"
            defaultValue="100"
            min="0"
            max="100"
            type="range"
          />
        </div>
        <div className="timeline-current">
          <span>目前</span>
          <strong>{gameData.last_target.period}</strong>
        </div>
      </div>

      <div className="error-band">
        <div className="error-heading">
          <ScanSearch size={31} />
          <span>
            <strong>事後錯誤檢討</strong>
            <small>
              上一期 {target ? formatDate(target.date) : "—"} ·{" "}
              {target?.period ?? "—"}
            </small>
          </span>
        </div>
        <div className="error-stat">
          <span>上一期最佳</span>
          <strong>{error?.best_selected_main_hits ?? "—"}/6</strong>
        </div>
        <div className="error-stat">
          <span>漏號</span>
          <strong className="is-coral">
            {error?.missed_actual_numbers?.join(" ") || "無"}
          </strong>
        </div>
        <div className="error-stat">
          <span>事後選擇遺憾</span>
          <strong className="is-coral">
            {(error?.hindsight_selection_regret ?? 0).toFixed(2)}
          </strong>
        </div>
        <button type="button" onClick={onOpenHistory}>
          檢視完整錯誤報告 <ArrowRight size={18} />
        </button>
      </div>
    </section>
  );
}
