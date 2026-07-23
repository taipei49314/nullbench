import {
  Activity,
  GitBranch,
  Radar,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState } from "react";

const EXPERTS = [
  ["overfit_guard", "H4", "反過度擬合"],
  ["regime_shift", "H2", "狀態轉換"],
  ["structural_bias", "H3", "結構偏差"],
  ["temporal_dependency", "H1", "時間依賴"],
  ["debate_consensus", "Σ", "辯論共識"],
  ["uniform", "H0", "均勻基準"],
];

const TABS = [
  ["weights", "即時權重"],
  ["evidence", "盲測證據"],
  ["contract", "升級規則"],
];

function signed(value, digits = 4) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function percent(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number)
    ? `${(number * 100).toFixed(digits)}%`
    : "—";
}

export default function SwitchingBayesPanel({ activeGame, study }) {
  const [tab, setTab] = useState("weights");
  const summary = study?.prequential_summary?.[activeGame];
  const model = study?.final_models?.[activeGame];
  const rows = useMemo(() => {
    const weights = model?.main_prior_weights ?? {};
    return EXPERTS.map(([id, code, name]) => ({
      id,
      code,
      name,
      weight: Number(weights[id] ?? 0),
    })).toSorted(
      (left, right) =>
        right.weight - left.weight ||
        left.code.localeCompare(right.code),
    );
  }, [model]);

  if (!summary || !model) {
    return (
      <section className="switching-bayes-panel is-unavailable">
        <Radar size={25} />
        <div>
          <strong>未知生成器證據層尚未就緒</strong>
          <p>{study?.error ?? "等待第一次完整盲測研究產物。"}</p>
        </div>
      </section>
    );
  }

  const rank =
    summary.top_30_hit_excess_vs_label_symmetry
      ?.debate_consensus;
  const regret = summary.main_exact_subset_regret_vs_uniform;
  const floor =
    Number(study?.methodology?.minimum_next_prior_weight) || 0;
  const promoted = study?.decision?.belief_layer_promoted === true;
  const pending = study?.forward_loop?.pending?.find(
    (row) => row.game === activeGame,
  );

  return (
    <section className="switching-bayes-panel">
      <header className="switching-bayes-head">
        <div className="switching-bayes-title">
          <Radar size={25} />
          <span>
            <strong>未知生成器 · SWITCHING BAYES</strong>
            <small>
              {pending
                ? `下期已封存 ${pending.target.period} · 揭曉後自動結算`
                : "完整六號 likelihood · 揭曉後才更新 · 機制可重新翻盤"}
            </small>
          </span>
        </div>
        <div
          className={`switching-bayes-state ${
            promoted ? "is-promoted" : ""
          }`}
        >
          <i />
          <span>
            <small>目前決策</small>
            <strong>
              {promoted ? "BELIEF PROMOTED" : "FUTURE SHADOW"}
            </strong>
          </span>
        </div>
        <nav aria-label="Switching Bayes 檢視模式">
          {TABS.map(([id, label]) => (
            <button
              aria-pressed={tab === id}
              className={tab === id ? "is-active" : ""}
              key={id}
              type="button"
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      {tab === "weights" ? (
        <div className="switching-weight-view">
          <div className="switching-weight-list">
            {rows.map((row) => (
              <div className="switching-weight-row" key={row.id}>
                <b>{row.code}</b>
                <span>
                  <strong>{row.name}</strong>
                  <i>
                    <em
                      style={{
                        width: `${Math.max(
                          1.5,
                          row.weight * 100,
                        )}%`,
                      }}
                    />
                  </i>
                </span>
                <output>{percent(row.weight)}</output>
              </div>
            ))}
          </div>
          <aside className="switching-recovery-note">
            <GitBranch size={22} />
            <div>
              <small>REGIME RECOVERY</small>
              <strong>任何假設都不會被永久歸零</strong>
              <p>
                每次揭曉後保留至少 {percent(floor, 3)} 的下一期
                prior；如果生成機制改變，H1–H4 可以重新取得主導權。
              </p>
            </div>
          </aside>
        </div>
      ) : null}

      {tab === "evidence" ? (
        <div className="switching-evidence-view">
          <article>
            <Activity size={22} />
            <span>
              <small>HOLDOUT TOP-30 超額命中</small>
              <strong>{signed(rank?.holdout_mean, 3)}</strong>
              <p>
                95% CI {signed(rank?.holdout_ci_low, 3)} ～{" "}
                {signed(rank?.holdout_ci_high, 3)}
              </p>
            </span>
          </article>
          <article>
            <ShieldCheck size={22} />
            <span>
              <small>完整六號 regret vs H0</small>
              <strong>{signed(regret?.holdout_mean, 6)}</strong>
              <p>負值才代表機率品質優於均勻基準</p>
            </span>
          </article>
          <div className="switching-evidence-verdict">
            <strong>有正向跡象，但尚未證明。</strong>
            <p>
              共識 top-30 在 holdout 平均多命中{" "}
              {signed(rank?.holdout_mean, 3)} 個主號，但信賴區間仍跨過
              0；目前不能誠實宣稱「比較準」。
            </p>
          </div>
        </div>
      ) : null}

      {tab === "contract" ? (
        <div className="switching-contract-view">
          <div>
            <b>01</b>
            <span>
              <strong>開獎前封存</strong>
              <p>H1–H4 完整機率、辯論共識與 H0 同時鎖定。</p>
            </span>
          </div>
          <div>
            <b>02</b>
            <span>
              <strong>完整結果結算</strong>
              <p>評分六號無序組合，不用三組抽樣提案冒充信念。</p>
            </span>
          </div>
          <div>
            <b>03</b>
            <span>
              <strong>只更新下一期</strong>
              <p>fixed-share 允許換機制；禁止回填已開出的期別。</p>
            </span>
          </div>
          <div>
            <b>04</b>
            <span>
              <strong>證據通過才升級</strong>
              <p>現在仍用共識排序 + 30 主號互斥的最大覆蓋出號。</p>
            </span>
          </div>
        </div>
      ) : null}
    </section>
  );
}
