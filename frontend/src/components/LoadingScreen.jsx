import {
  Activity,
  BrainCircuit,
  Check,
  CloudDownload,
  History,
  RadioTower,
  ShieldCheck,
} from "lucide-react";

const STEPS = [
  ["queued", "喚醒背景 Loop", RadioTower],
  ["checking", "偵測官方開獎", CloudDownload],
  ["reviewing", "檢討新開獎", History],
  ["optimizing", "更新 Agent 狀態", BrainCircuit],
  ["preregistering", "凍結前向 A/B", ShieldCheck],
  ["ready", "準備下一期候選", Check],
];

export default function LoadingScreen({ error, syncState }) {
  const currentIndex = Math.max(
    0,
    STEPS.findIndex(([phase]) => phase === syncState?.phase),
  );
  return (
    <main className="loading-screen">
      <div className="loading-mark">
        <span>LOTTO</span>
        <i>//</i>
        <span>LAB</span>
      </div>
      {error ? (
        <>
          <strong>模擬資料尚未就緒</strong>
          <p>{error}</p>
          <code>python lotto.py loop</code>
        </>
      ) : (
        <>
          <Activity size={25} />
          <strong>{syncState?.message || "正在同步演算議會"}</strong>
          <div className="sync-steps" aria-label="自動同步進度">
            {STEPS.map(([phase, label, Icon], index) => {
              const complete =
                syncState?.phase === "ready" || index < currentIndex;
              const active = phase === syncState?.phase;
              return (
                <span
                  className={`${complete ? "is-complete" : ""} ${
                    active ? "is-active" : ""
                  }`}
                  key={phase}
                >
                  <i>{complete ? <Check size={15} /> : <Icon size={15} />}</i>
                  {label}
                </span>
              );
            })}
          </div>
          <span className="loading-line" />
        </>
      )}
    </main>
  );
}
