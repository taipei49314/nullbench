import { Activity } from "lucide-react";

export default function LoadingScreen({ error }) {
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
          <strong>正在同步演算議會</strong>
          <span className="loading-line" />
        </>
      )}
    </main>
  );
}
