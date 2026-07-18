import {
  Activity,
  ArrowRight,
  Crosshair,
  FlaskConical,
  GitCompareArrows,
  Replace,
  ShieldAlert,
  UsersRound,
} from "lucide-react";
import { useState } from "react";

import { AGENTS, GAME_LABELS, formatDate } from "../domain";

const MODE_OPTIONS = [
  { id: "calibration", label: "評論校準" },
  { id: "redundancy", label: "聲音重複" },
];

function signed(value, digits = 3) {
  if (value == null) return "—";
  const formatted = Number(value).toFixed(digits);
  return value > 0 ? `+${formatted}` : formatted;
}

function percent(value, digits = 1) {
  if (value == null) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function correlation(value) {
  return value == null ? "固定基準" : signed(value, 3);
}

function TraceChart({ traces, selectedPeriod, onSelect }) {
  return (
    <div className="research-trace-chart">
      <div className="trace-scale" aria-hidden="true">
        <span>6</span>
        <span>3</span>
        <span>0</span>
      </div>
      <div
        className="trace-bars"
        role="list"
        aria-label="最近 holdout 逐期最佳主號命中比較"
      >
        {traces.map((trace) => (
          <button
            aria-label={`第 ${trace.period} 期，現行 ${trace.baseline_best_main_hits}，影子 ${trace.replacement_best_main_hits}`}
            className={
              trace.period === selectedPeriod ? "is-active" : ""
            }
            key={trace.period}
            onClick={() => onSelect(trace.period)}
            role="listitem"
            title={`${formatDate(trace.date)} · ${trace.period}`}
            type="button"
          >
            <i
              className="is-baseline"
              style={{
                "--hit-height": `${Math.max(
                  5,
                  (trace.baseline_best_main_hits / 6) * 100,
                )}%`,
              }}
            />
            <i
              className="is-shadow"
              style={{
                "--hit-height": `${Math.max(
                  5,
                  (trace.replacement_best_main_hits / 6) * 100,
                )}%`,
              }}
            />
          </button>
        ))}
      </div>
    </div>
  );
}

function AgentEvidence({ row }) {
  return (
    <aside className="research-agent-evidence">
      <header>
        <span className={`agent-signal is-${AGENTS[row.agent].color}`}>
          {AGENTS[row.agent].index}
        </span>
        <span>
          <strong>{row.agent_name}</strong>
          <small>{AGENTS[row.agent].doctrine}</small>
        </span>
      </header>
      <dl>
        <div>
          <dt>提案平均主號命中</dt>
          <dd>{row.proposal_mean_main_hits.toFixed(3)}</dd>
        </div>
        <div>
          <dt>每期獨有候選號碼</dt>
          <dd>{row.unique_candidate_numbers.toFixed(2)}</dd>
        </div>
        <div>
          <dt>現行五注席次占比</dt>
          <dd>{percent(row.selected_ticket_share)}</dd>
        </div>
        <div>
          <dt>移除後最佳命中差</dt>
          <dd>{signed(row.leaveout_delta_best_main_hits, 3)}</dd>
        </div>
      </dl>
      <div className="replacement-readout">
        <span>改由覆蓋稽核員後</span>
        <strong>{signed(row.replacement_delta_best_main_hits, 4)}</strong>
        <small>
          95% CI {signed(row.replacement_delta_best_main_hits_ci_low, 4)}{" "}
          至 {signed(row.replacement_delta_best_main_hits_ci_high, 4)}
        </small>
      </div>
      <p>
        聯集命中 {signed(row.replacement_delta_union_main_hits, 3)} ·
        聯集大小 {signed(row.replacement_delta_union_size, 2)} ·
        五注保留 {percent(row.replacement_selection_overlap)}
      </p>
    </aside>
  );
}

export default function ResearchView({
  activeGame,
  onGameChange,
  study,
}) {
  const selectedReplacement = study.selected_replacements[activeGame];
  const holdoutAgents = study.agent_quality.filter(
    (row) => row.game === activeGame && row.split === "holdout",
  );
  const critics = study.critic_quality.filter(
    (row) => row.game === activeGame && row.split === "holdout",
  );
  const criticPairs = study.critic_pair_redundancy.filter(
    (row) => row.game === activeGame && row.split === "holdout",
  );
  const variants = study.judge_sensitivity.filter(
    (row) => row.game === activeGame && row.split === "holdout",
  );
  const traces = study.recent_holdout_trace[activeGame];
  const [selectedAgent, setSelectedAgent] = useState(
    selectedReplacement.removed_agent,
  );
  const [selectedPeriod, setSelectedPeriod] = useState(
    traces.at(-1)?.period ?? null,
  );
  const [selectedVariant, setSelectedVariant] = useState(
    variants.find((row) => row.variant === "diversity_off")?.variant ??
      variants[0]?.variant,
  );
  const [debateMode, setDebateMode] = useState("calibration");

  const agentRow =
    holdoutAgents.find((row) => row.agent === selectedAgent) ??
    holdoutAgents[0];
  const trace =
    traces.find((row) => row.period === selectedPeriod) ?? traces.at(-1);
  const variant =
    variants.find((row) => row.variant === selectedVariant) ?? variants[0];
  const promoted =
    study.conclusion.status === "promote_candidate";

  return (
    <div className="workspace-view research-view">
      <header className="research-heading">
        <div>
          <span className="research-mark">
            <FlaskConical size={21} />
          </span>
          <span>
            <h1>影子策略實驗室</h1>
            <p>
              4,082 期配對重播 · development 選擇 · holdout
              一次性驗證 · 不改動下一期正式號碼
            </p>
          </span>
        </div>
        <div className="research-game-switch" aria-label="研究遊戲">
          {Object.entries(GAME_LABELS).map(([game, label]) => (
            <button
              className={activeGame === game ? "is-active" : ""}
              key={game}
              onClick={() => onGameChange(game)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <div
          className={`research-gate ${promoted ? "is-promoted" : "is-held"}`}
        >
          <ShieldAlert size={19} />
          <span>
            <small>JOINT PROMOTION GATE</small>
            <strong>
              {promoted ? "PROMOTE CANDIDATE" : "SHADOW ONLY · NOT PROMOTED"}
            </strong>
          </span>
        </div>
      </header>

      <section className="research-hero-grid">
        <div className="replacement-brief">
          <header>
            <Replace size={22} />
            <span>
              <small>DEVELOPMENT-SELECTED REPLACEMENT</small>
              <strong>
                {selectedReplacement.removed_agent_name}
                <ArrowRight size={18} />
                {selectedReplacement.candidate_agent_name}
              </strong>
            </span>
          </header>
          <div className="replacement-kpis">
            <div>
              <small>Holdout 最佳命中差</small>
              <strong>
                {signed(
                  selectedReplacement.holdout
                    .replacement_delta_best_main_hits,
                  4,
                )}
              </strong>
            </div>
            <div>
              <small>95% 區間</small>
              <strong>
                {signed(
                  selectedReplacement.holdout
                    .replacement_delta_best_main_hits_ci_low,
                  4,
                )}{" "}
                —{" "}
                {signed(
                  selectedReplacement.holdout
                    .replacement_delta_best_main_hits_ci_high,
                  4,
                )}
              </strong>
            </div>
            <div>
              <small>主號聯集命中差</small>
              <strong>
                {signed(
                  selectedReplacement.holdout
                    .replacement_delta_union_main_hits,
                  4,
                )}
              </strong>
            </div>
          </div>
          <p>
            {activeGame === "super"
              ? "威力彩單獨通過，但聯合閘門要求兩款遊戲都通過，故不升級。"
              : "大樂透區間仍跨過 0，不能把正平均值當成已證明優勢。"}
          </p>
        </div>

        <div className="trace-panel">
          <header>
            <Activity size={21} />
            <span>
              <strong>最近 {traces.length} 期 HOLDOUT</strong>
              <small>點任一期比較現行議會與影子替換</small>
            </span>
            <span className="trace-legend">
              <i className="is-baseline" /> 現行
              <i className="is-shadow" /> 影子
            </span>
          </header>
          <TraceChart
            onSelect={setSelectedPeriod}
            selectedPeriod={trace?.period}
            traces={traces}
          />
          {trace ? (
            <div className="trace-detail">
              <span>
                <small>{formatDate(trace.date)}</small>
                <strong>{trace.period}</strong>
              </span>
              <span>
                <small>現行最佳</small>
                <strong>{trace.baseline_best_main_hits}/6</strong>
              </span>
              <span>
                <small>影子最佳</small>
                <strong className="is-lime">
                  {trace.replacement_best_main_hits}/6
                </strong>
              </span>
              <span>
                <small>聯集命中</small>
                <strong>
                  {trace.baseline_union_main_hits}
                  <i> → </i>
                  {trace.replacement_union_main_hits}
                </strong>
              </span>
              <span>
                <small>五注保留</small>
                <strong>{percent(trace.selection_overlap)}</strong>
              </span>
            </div>
          ) : null}
        </div>
      </section>

      <section className="agent-quality-lab">
        <header className="research-section-heading">
          <UsersRound size={21} />
          <span>
            <strong>AGENT QUALITY / REPLACEMENT ABLATION</strong>
            <small>點選席位查看移除與替換的配對結果</small>
          </span>
        </header>
        <div className="agent-quality-layout">
          <div className="agent-quality-list">
            <div className="agent-quality-head">
              <span>席位</span>
              <span>提案命中</span>
              <span>獨有號碼</span>
              <span>移除後</span>
              <span>替換後</span>
              <span>證據</span>
            </div>
            {holdoutAgents.map((row) => {
              const isFrozenSelection =
                row.agent === selectedReplacement.removed_agent;
              const evidenceLabel = isFrozenSelection
                ? row.action === "replacement_supported"
                  ? "SUPPORTED"
                  : row.action === "keep_existing"
                    ? "KEEP"
                    : "UNCERTAIN"
                : "EXPLORE";
              return (
                <button
                  className={
                    row.agent === selectedAgent ? "is-active" : ""
                  }
                  key={row.agent}
                  onClick={() => setSelectedAgent(row.agent)}
                  type="button"
                >
                  <span>
                    <i className={`is-${AGENTS[row.agent].color}`}>
                      {AGENTS[row.agent].index}
                    </i>
                    <strong>{row.agent_name}</strong>
                  </span>
                  <b>{row.proposal_mean_main_hits.toFixed(3)}</b>
                  <b>{row.unique_candidate_numbers.toFixed(2)}</b>
                  <b>{signed(row.leaveout_delta_best_main_hits, 3)}</b>
                  <b
                    className={
                      row.replacement_delta_best_main_hits > 0
                        ? "is-positive"
                        : "is-negative"
                    }
                  >
                    {signed(row.replacement_delta_best_main_hits, 3)}
                  </b>
                  <em
                    className={
                      isFrozenSelection
                        ? `is-${row.action}`
                        : "is-exploratory"
                    }
                  >
                    {evidenceLabel}
                  </em>
                </button>
              );
            })}
          </div>
          <AgentEvidence row={agentRow} />
        </div>
      </section>

      <section className="research-lower-grid">
        <div className="debate-quality-panel">
          <header className="research-section-heading">
            <Crosshair size={21} />
            <span>
              <strong>DEBATE EVIDENCE</strong>
              <small>評論只能當結構評議，不能冒充命中預測</small>
            </span>
            <div className="research-mode-switch">
              {MODE_OPTIONS.map((option) => (
                <button
                  className={
                    debateMode === option.id ? "is-active" : ""
                  }
                  key={option.id}
                  onClick={() => setDebateMode(option.id)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </header>
          {debateMode === "calibration" ? (
            <div className="critic-quality-table">
              <div>
                <span>評論者</span>
                <span>分數標準差</span>
                <span>命中相關</span>
                <span>高分組命中差</span>
              </div>
              {critics.map((row) => (
                <div key={row.critic}>
                  <strong>{row.critic_name}</strong>
                  <b>{row.score_std.toFixed(3)}</b>
                  <b>{correlation(row.pearson_score_to_actual)}</b>
                  <b>{signed(row.top_quartile_actual_lift, 3)}</b>
                </div>
              ))}
            </div>
          ) : (
            <div className="critic-pair-table">
              {criticPairs.map((row) => (
                <div key={`${row.left_critic}:${row.right_critic}`}>
                  <span>
                    <strong>{row.left_name}</strong>
                    <i>×</i>
                    <strong>{row.right_name}</strong>
                  </span>
                  <span>
                    <small>聲音相關</small>
                    <b>{correlation(row.score_correlation)}</b>
                  </span>
                  <span>
                    <small>平均分差</small>
                    <b>{row.mean_absolute_score_gap.toFixed(3)}</b>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="judge-sensitivity-panel">
          <header className="research-section-heading">
            <GitCompareArrows size={21} />
            <span>
              <strong>JUDGE SENSITIVITY</strong>
              <small>一次只關閉一個規則旋鈕</small>
            </span>
          </header>
          <div className="sensitivity-tabs">
            {variants.map((row) => (
              <button
                className={
                  row.variant === selectedVariant ? "is-active" : ""
                }
                key={row.variant}
                onClick={() => setSelectedVariant(row.variant)}
                type="button"
              >
                {row.variant_label}
              </button>
            ))}
          </div>
          {variant ? (
            <div className="sensitivity-readout">
              <div>
                <small>原五注保留</small>
                <strong>{percent(variant.selection_overlap)}</strong>
              </div>
              <div>
                <small>完全相同率</small>
                <strong>{percent(variant.exact_selection_rate)}</strong>
              </div>
              <div>
                <small>最佳命中差</small>
                <strong>{signed(variant.delta_best_main_hits, 4)}</strong>
              </div>
              <div>
                <small>聯集命中差</small>
                <strong>{signed(variant.delta_union_main_hits, 4)}</strong>
              </div>
              <p>
                {variant.variant === "diversity_off"
                  ? "關閉五注重疊懲罰會明顯降低聯集覆蓋；這個旋鈕有實際組合功能。"
                  : "正負歷史差都未經前向預註冊，不用來直接調整下一期正式裁決。"}
              </p>
            </div>
          ) : null}
        </div>
      </section>

      <footer className="research-footer">
        <span>
          <FlaskConical size={17} />
          {study.experiment_id}
        </span>
        <strong>
          {study.conclusion.recommendation === "keep_as_shadow_only"
            ? "正式五席維持不變"
            : "候選通過聯合閘門"}
        </strong>
        <code>{study.generated_at}</code>
      </footer>
    </div>
  );
}
