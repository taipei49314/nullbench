import { Check, LockKeyhole, ScanSearch } from "lucide-react";

import { AGENTS, getWalkForwardEvidence } from "../domain";

function EvidenceChart({ hypotheses, rows }) {
  const width = 760;
  const height = 118;
  const padding = 12;
  const series = hypotheses.map((hypothesis) => {
    let cumulative = 0;
    return {
      ...hypothesis,
      points: rows.map((row, index) => {
        cumulative += Number(row.skills[hypothesis.id] ?? 0) * 1000;
        return {
          x:
            padding +
            (index / Math.max(1, rows.length - 1)) *
              (width - padding * 2),
          value: cumulative,
        };
      }),
    };
  });
  const values = series.flatMap((item) =>
    item.points.map((point) => point.value),
  );
  const maximum = Math.max(1, ...values.map((value) => Math.abs(value)));
  const y = (value) =>
    height / 2 - (value / maximum) * (height / 2 - padding);

  return (
    <svg
      aria-label="各假說相對 H0 的累積 proper score"
      className="walk-forward-chart"
      preserveAspectRatio="none"
      role="img"
      viewBox={`0 0 ${width} ${height}`}
    >
      <line x1="0" x2={width} y1={height / 2} y2={height / 2} />
      {series.map((item) => {
        const points = item.points
          .map((point) => `${point.x},${y(point.value)}`)
          .join(" ");
        return (
          <polyline
            className={`is-${item.color}`}
            key={item.id}
            points={points}
          />
        );
      })}
    </svg>
  );
}

export default function WalkForwardDock({
  events,
  hypotheses,
  onOpenHistory,
}) {
  const rows = getWalkForwardEvidence(events);
  const visible = rows.slice(-10);
  const latest = visible.at(-1);
  return (
    <section className="walk-forward-dock">
      <div className="walk-forward-heading">
        <span>
          <strong>走查驗證時間軸</strong>
          <small>Walk-Forward · 預測先封存，結果後揭曉</small>
        </span>
        <button type="button" onClick={onOpenHistory}>
          <ScanSearch size={17} />
          完整回放
        </button>
      </div>

      <div className="walk-forward-periods">
        {visible.map((row, index) => (
          <button
            className={index === visible.length - 1 ? "is-current" : ""}
            key={`${row.period}:${index}`}
            title={`第 ${row.period} 期：${
              row.revealed ? "已揭曉" : "已封存"
            }`}
            type="button"
          >
            <span>{String(row.period).slice(-6)}</span>
            <i>
              {row.revealed ? (
                <Check size={14} />
              ) : (
                <LockKeyhole size={13} />
              )}
            </i>
            <small>{row.revealed ? "已揭曉" : "預測封存"}</small>
          </button>
        ))}
        <div className="future-period">
          <i />
          <span>下一期</span>
          <small>等待辯論</small>
        </div>
      </div>

      <div className="walk-forward-evidence">
        <div>
          <span>
            <strong>累積切分數</strong>
            <small>相對 H0 · 越高越好</small>
          </span>
          <EvidenceChart hypotheses={hypotheses} rows={visible} />
        </div>
        <aside>
          {hypotheses.map((hypothesis) => {
            const value =
              Number(
                hypothesis.blind_evidence?.mean_skill_vs_h0 ?? 0,
              ) * 1000;
            return (
              <span key={hypothesis.id}>
                <i className={`is-${hypothesis.color}`} />
                <strong>
                  {AGENTS[hypothesis.id]?.code} {hypothesis.name}
                </strong>
                <b>
                  {value >= 0 ? "+" : ""}
                  {value.toFixed(2)}
                </b>
              </span>
            );
          })}
          <p>
            最新已揭曉期最佳：{latest?.bestHits ?? "—"}/6。單期命中不直接
            決定權重，更新依完整機率分布的 proper score。
          </p>
        </aside>
      </div>
    </section>
  );
}
