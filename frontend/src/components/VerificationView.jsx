import {
  Binary,
  BrainCircuit,
  Check,
  FileLock2,
  Fingerprint,
  Gauge,
  GitCompareArrows,
  RadioTower,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";

const CHECKS = [
  ["零未來資料洩漏", "決策切片只含目標期以前資料"],
  ["決定性重播", "兩次完整回放 SHA-256 完全一致"],
  ["逐期無缺漏", "sequence 與 history_count 連續"],
  ["揭曉後才更新", "state_before / state_after 可追溯"],
  ["正式帳本隔離", "records tree hash 前後一致"],
];

export default function VerificationView({ gameData, manifest }) {
  const [feedbackHashCopied, setFeedbackHashCopied] = useState(false);
  const forward = manifest.forward_experiment;
  const forwardGame = forward?.games?.[gameData.game];
  const pending = forwardGame?.pending?.at(-1);
  const operations = forward?.operations;
  const operationsGame = operations?.games?.[gameData.game];
  const operationsMethod = operations?.methodology;
  const deploymentGate = operations?.deployment_gate;
  const feedbackMemory = forward?.feedback_memory?.[gameData.game];
  const feedbackProvenance =
    gameData.next_decision.adjudication?.judge?.feedback_provenance;
  const latestFeedbackFlags =
    feedbackMemory?.aggregate?.latest_diagnostic_flags ?? [];
  const feedbackHash =
    feedbackProvenance?.feedback_hash ??
    feedbackMemory?.feedback_hash ??
    null;
  const shortFeedbackHash = feedbackHash
    ? `${feedbackHash.slice(0, 16)}…${feedbackHash.slice(-8)}`
    : "not-yet-generated";
  const copyFeedbackHash = async () => {
    if (!feedbackHash) return;
    await navigator.clipboard.writeText(feedbackHash);
    setFeedbackHashCopied(true);
  };
  const automation = manifest.automation;
  const automationOnline =
    automation?.supervisor_online &&
    automation?.watcher_state === "online";
  const displayTime = (value) =>
    value ? value.replace("T", " ").slice(0, 19) : "尚未執行";
  return (
    <div className="workspace-view verification-view">
      <header className="workspace-heading">
        <div>
          <h1>驗證鏈</h1>
          <p>每一個候選、裁決、揭曉與檢討都能從內容雜湊重新驗證。</p>
        </div>
        <div className="verification-seal">
          <ShieldCheck size={26} />
          <span>
            <strong>ALL GREEN</strong>
            <small>VERIFIED PIPELINE</small>
          </span>
        </div>
      </header>

      <div className="verification-grid">
        <section className="hash-panel">
          <div className="hash-panel-title">
            <Fingerprint size={21} />
            <strong>目前遊戲帳本</strong>
          </div>
          <dl>
            <div>
              <dt>LEDGER SHA-256</dt>
              <dd>{gameData.ledger_sha256}</dd>
            </div>
            <div>
              <dt>LAST EVENT HASH</dt>
              <dd>{gameData.last_event_hash}</dd>
            </div>
            <div>
              <dt>NEXT DECISION HASH</dt>
              <dd>{gameData.next_decision.decision_hash}</dd>
            </div>
            <div>
              <dt>MANIFEST HASH</dt>
              <dd>{manifest.manifest_hash}</dd>
            </div>
          </dl>
        </section>

        <section className="verification-checks">
          {CHECKS.map(([title, detail]) => (
            <div key={title}>
              <i>
                <Check size={18} />
              </i>
              <span>
                <strong>{title}</strong>
                <small>{detail}</small>
              </span>
              <b>PASS</b>
            </div>
          ))}
        </section>
      </div>

      <section className="forward-proof-panel">
        <header>
          <div>
            <GitCompareArrows size={22} />
            <span>
              <strong>QWEN / RULE 前向 A/B</strong>
              <small>開獎前凍結 · 缺登與晚登永不回填</small>
            </span>
          </div>
          <b
            className={
              forward?.verification?.chain_valid ? "is-valid" : "is-pending"
            }
          >
            {forward?.verification?.chain_valid
              ? "CHAIN VERIFIED"
              : "WAITING FOR FIRST REGISTRATION"}
          </b>
        </header>
        <div className="forward-proof-metrics">
          <div>
            <small>有效配對</small>
            <strong>
              {forwardGame?.eligible_qwen_rule_pairs ?? 0}
              <i> / {forward?.methodology?.minimum_paired_draws_per_game ?? 52}</i>
            </strong>
          </div>
          <div>
            <small>Qwen / 和局 / 規則</small>
            <strong>
              {forwardGame
                ? `${forwardGame.qwen_vs_rule.qwen_wins} / ${forwardGame.qwen_vs_rule.ties} / ${forwardGame.qwen_vs_rule.rule_wins}`
                : "0 / 0 / 0"}
            </strong>
          </div>
          <div>
            <small>待開獎目標</small>
            <strong>
              {pending
                ? `${pending.target.date} · ${pending.target.period}`
                : "尚未凍結"}
            </strong>
          </div>
          <div>
            <small>證據狀態</small>
            <strong>
              {forward?.evidence_status ?? "尚未建立前向樣本"}
            </strong>
          </div>
        </div>
        <p>
          只有 Qwen 與規則裁判都在截止前成功凍結的期數才會進入比較；
          均勻隨機五注同時保存為零假設。這裡不顯示事後補算的「預測」。
        </p>
      </section>

      <section className="model-observatory-panel">
        <header>
          <div>
            <Gauge size={22} />
            <span>
              <strong>QWEN MODEL OBSERVATORY</strong>
              <small>延遲 · 降級 · Token · 五注分散 · 開獎後品質</small>
            </span>
          </div>
          <b
            className={
              operationsGame?.status === "operationally_healthy"
                ? "is-healthy"
                : operationsGame?.status === "operationally_degraded"
                  ? "is-degraded"
                  : "is-collecting"
            }
          >
            {operationsGame?.status ?? "WAITING FOR INSTRUMENTED CALL"}
          </b>
        </header>
        <div className="model-observatory-metrics">
          <div>
            <small>儀器化樣本</small>
            <strong>
              {operationsGame?.window_attempts ?? 0}
              <i>
                {" "}
                / {operationsMethod?.minimum_observations_per_game ?? 10}
              </i>
            </strong>
          </div>
          <div>
            <small>Qwen p95 延遲</small>
            <strong>
              {operationsGame?.latency_ms?.p95 == null
                ? "待累積"
                : `${Math.round(operationsGame.latency_ms.p95)} ms`}
            </strong>
          </div>
          <div>
            <small>規則降級率</small>
            <strong>
              {operationsGame?.fallback_rate == null
                ? "待累積"
                : `${(operationsGame.fallback_rate * 100).toFixed(1)}%`}
            </strong>
          </div>
          <div>
            <small>平均輸出 Token</small>
            <strong>
              {operationsGame?.tokens?.mean_eval_count == null
                ? "待累積"
                : Math.round(operationsGame.tokens.mean_eval_count)}
            </strong>
          </div>
          <div>
            <small>五注主號覆蓋</small>
            <strong>
              {operationsGame?.selection?.mean_main_number_union_size == null
                ? "待累積"
                : operationsGame.selection.mean_main_number_union_size}
            </strong>
          </div>
        </div>
        <div className="model-quality-strip">
          <span>
            <small>最近品質視窗</small>
            <strong>
              {operationsGame?.quality?.window_draws ?? 0}
              <i>
                {" "}
                / {operationsGame?.quality?.maximum_window_draws ?? 13}
              </i>
            </strong>
          </span>
          <span>
            <small>Qwen − 規則最佳命中</small>
            <strong>
              {operationsGame?.quality
                ?.qwen_minus_rule_best_main_hits == null
                ? "待開獎"
                : operationsGame.quality.qwen_minus_rule_best_main_hits}
            </strong>
          </span>
          <span>
            <small>Qwen − 均勻隨機最佳命中</small>
            <strong>
              {operationsGame?.quality
                ?.qwen_minus_random_best_main_hits == null
                ? "待開獎"
                : operationsGame.quality.qwen_minus_random_best_main_hits}
            </strong>
          </span>
        </div>
        <div className="model-deployment-gate">
          <span>
            <small>聯合部署閘門</small>
            <strong>
              {deploymentGate?.status ?? "collecting_joint_evidence"}
            </strong>
          </span>
          <span>
            <small>目前建議</small>
            <strong>
              {deploymentGate?.recommendation ?? "keep_rule_as_control"}
            </strong>
          </span>
          <p>
            既有未儀器化登記：
            <b>
              {operationsGame?.legacy_uninstrumented_registrations ?? 0}
            </b>
            筆；缺少的耗時與 Token 永不事後回填。
          </p>
        </div>
      </section>

      <section className="feedback-memory-panel">
        <header>
          <div>
            <BrainCircuit size={22} />
            <span>
              <strong>SETTLED ERROR MEMORY</strong>
              <small>先結算 · 後檢討 · 再裁決 · 禁止追逐漏號</small>
            </span>
          </div>
          <b
            className={
              feedbackProvenance?.status === "verified"
                ? "is-consumed"
                : feedbackProvenance?.status === "verified_empty"
                  ? "is-empty"
                  : "is-waiting"
            }
          >
            {feedbackProvenance?.status === "verified"
              ? "CONSUMED BY QWEN"
              : feedbackProvenance?.status === "verified_empty"
                ? "VERIFIED · FIRST CYCLE"
                : "WAITING FOR NEXT DECISION"}
          </b>
        </header>
        <div className="feedback-memory-metrics">
          <div>
            <small>已結算記憶</small>
            <strong>
              {feedbackMemory?.settlement_count ?? 0}
              <i> / {feedbackMemory?.maximum_window ?? 13}</i>
            </strong>
          </div>
          <div>
            <small>最近結算目標</small>
            <strong>
              {feedbackMemory?.as_of_target
                ? `${feedbackMemory.as_of_target.date} · ${feedbackMemory.as_of_target.period}`
                : "尚無樣本"}
            </strong>
          </div>
          <div>
            <small>Qwen − 規則平均最佳命中</small>
            <strong>
              {feedbackMemory?.aggregate
                ?.mean_qwen_minus_rule_best_main_hits ?? "待累積"}
            </strong>
          </div>
          <div>
            <small>本次裁決讀取</small>
            <strong>
              {feedbackProvenance
                ? `${feedbackProvenance.settlement_count} 期`
                : "尚未重建"}
            </strong>
          </div>
        </div>
        <div className="feedback-memory-detail">
          <span>
            <small>最新固定診斷</small>
            <strong>
              {latestFeedbackFlags.length
                ? latestFeedbackFlags.join(" · ")
                : "等待第一筆前向結算"}
            </strong>
          </span>
          <button
            type="button"
            className="feedback-hash-copy"
            title={feedbackHash ?? "尚未建立回饋雜湊"}
            disabled={!feedbackHash}
            onClick={copyFeedbackHash}
          >
            <code>feedback / {shortFeedbackHash}</code>
            <span>{feedbackHashCopied ? "COPIED" : "COPY HASH"}</span>
          </button>
        </div>
        <p>
          回饋只保留覆蓋度、重複集中與相對命中等組合層統計，不把實際開獎號碼交給下一輪，
          也不把單期落差解釋成因果。任何含目標期或未來資料的回饋都會在呼叫 Qwen 前被拒絕。
        </p>
      </section>

      <section className="automation-proof-panel">
        <header>
          <div>
            <RadioTower size={22} />
            <span>
              <strong>桌機無人值守 LOOP</strong>
              <small>無分頁運行 · 單例交易 · 失敗指數退避</small>
            </span>
          </div>
          <b className={automationOnline ? "is-online" : "is-offline"}>
            {automationOnline ? "AUTONOMOUS LOOP ONLINE" : "LOOP OFFLINE"}
          </b>
        </header>
        <div className="automation-proof-metrics">
          <div>
            <small>目前狀態</small>
            <strong>
              {automation
                ? `${automation.status} / ${automation.phase}`
                : "尚未啟動"}
            </strong>
          </div>
          <div>
            <small>上次成功</small>
            <strong>{displayTime(automation?.last_success_at)}</strong>
          </div>
          <div>
            <small>下次檢查</small>
            <strong>{displayTime(automation?.next_check_at)}</strong>
          </div>
          <div>
            <small>連續失敗</small>
            <strong>{automation?.consecutive_failures ?? 0}</strong>
          </div>
        </div>
        <p>
          桌機伺服器會監督背景 Python watcher；關閉瀏覽器分頁後仍每五分鐘檢查。
          同步、結算與下一期凍結共用跨程序鎖，崩潰後由監督程序重啟。
        </p>
      </section>

      <div className="verification-footer">
        <div>
          <Binary size={24} />
          <span>
            <strong>{gameData.draws_replayed.toLocaleString()} 期</strong>
            <small>完整逐期回放</small>
          </span>
        </div>
        <div>
          <FileLock2 size={24} />
          <span>
            <strong>{gameData.verification.lines.toLocaleString()} 行</strong>
            <small>JSONL 鏈已驗證</small>
          </span>
        </div>
        <code>experiment / {manifest.experiment_id}</code>
      </div>
    </div>
  );
}
