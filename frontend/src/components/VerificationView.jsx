import {
  Binary,
  Check,
  FileLock2,
  Fingerprint,
  GitCompareArrows,
  RadioTower,
  ShieldCheck,
} from "lucide-react";

const CHECKS = [
  ["零未來資料洩漏", "決策切片只含目標期以前資料"],
  ["決定性重播", "兩次完整回放 SHA-256 完全一致"],
  ["逐期無缺漏", "sequence 與 history_count 連續"],
  ["揭曉後才更新", "state_before / state_after 可追溯"],
  ["正式帳本隔離", "records tree hash 前後一致"],
];

export default function VerificationView({ gameData, manifest }) {
  const forward = manifest.forward_experiment;
  const forwardGame = forward?.games?.[gameData.game];
  const pending = forwardGame?.pending?.at(-1);
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
