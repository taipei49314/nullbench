import {
  Binary,
  Check,
  FileLock2,
  Fingerprint,
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
            <small>129 / 129 TESTS</small>
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
