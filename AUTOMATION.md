# 桌機背景 Loop 規格

## 目標

只要 `npm run dev` 的桌機伺服器仍在，關閉瀏覽器分頁也要每五分鐘完成一次：

1. 比對台彩官方當月資料。
2. 只結算已在開獎前凍結的 Qwen／規則／均勻隨機控制臂，以及新登記才有
   的 coverage shadow。
3. 建立不含原始號碼、最多 13 期的已結算錯誤回饋；若該期有 v3／v4 獲利
   子影子，同時彙總 eligible guarded／unconstrained 相對 coverage 的
   嚴格獲利與壓力淨額差。
4. 有新開獎才重建逐期 Agent 回放，讓 Qwen 讀取回饋後裁決下一期。
5. 先用最新揭曉更新 proper-score stacking 權重與候選，再更新並交叉驗證
   null-safe operational state；時間與權重跟隨 stacking，e-process
   從凍結基線加上帳本全部已預註冊 v7 score 決定性重建，v6 空窗不得
   事後回補，重跑不得重複計入。之後才凍結新的下一期
   控制臂與 coverage shadow；威力彩另凍結 guarded／
   unconstrained 獲利子影子、共同第二區 v4 paired shadow，以及不改主號
   的前五第二區配對子影子；兩款遊戲另凍結 v5/v6 probability stacking
   與 v7 null-safe paired shadow，更新前端
   可讀摘要。
6. 下一期凍結完成後，若 Agent 品質、共識完全分散五注、30 號標籤或
   五注分組或開獎機制訊號研究已落後，再唯讀重算五份研究結果。

固定交易順序與防追號契約見
[FORWARD_FEEDBACK.md](FORWARD_FEEDBACK.md)。回饋驗證或 Qwen 裁決失敗時，
會明確降級為可重現規則裁決；Qwen 臂標為不合格且不得冒充模型成功。
完整回放或帳本交易失敗時才會停止新目標登記並由下一輪重試。
前向摘要的共同 checkpoint 與多重比較規則由
[FORWARD_MONITORING_V2.md](FORWARD_MONITORING_V2.md) 凍結；背景 Loop 每輪
只能重建該契約，不能因新一期結果改 checkpoint 或 family 大小。

## 程序與故障模型

- Vite 桌機伺服器監督 `python lotto.py watch --interval 300 --quiet`。
- watcher 意外結束時，監督程序以最長 30 秒的指數退避重新啟動。
- 官方 API 或模型失敗時，watcher 以 30、60、120 秒遞增重試，最長 30 分鐘。
- 頁面 `/api/sync` 只寫入 wake request，不再另開一個會競爭帳本的同步程序。
- CLI `sync` 與 watcher 共用 OS 檔案鎖；程序死亡時作業系統會自動釋放鎖。

## 可稽核狀態

執行期檔案均在 `simulation/automation/`，不進 Git，也不修改正式 `records/`：

- `status.json`：目前 phase、心跳、上次成功、下次檢查、連續失敗與結果。
- `wake-request.json`：頁面要求提早執行的最後一個 request ID。
- `history.jsonl`：每輪成功／失敗的 append-only SHA-256 雜湊鏈。
- `sync.lock`：跨程序單例鎖。

背景 Loop 不會把「程序有在跑」解釋成號碼更準；它只保證同一個預先登記、
開獎後結算、再產生下一期登記的實驗契約持續執行。

會直接產生下一期號碼的 proper-score stacking 是唯一例外：它必須在新一期
登記前完成更新，並同步重建 top-k 決策強度稽核；任一失敗時停止該次新目標
登記，避免使用漏掉最新揭曉的權重或把不可辨識的差異冒充實質優勢。
其餘探索性影子研究的順序刻意排在前向 A/B 凍結之後。若研究失敗，已凍結的下一期
號碼仍維持不變；下一輪會因 `council_quality.json`、
`max_coverage.json`、`label_signal.json`、`partition_signal.json` 或
`mechanism_signal.json`
仍落後於模擬帳本而重試。研究只寫
`research/results/`，不寫正式 `records/` 或前向帳本。

## 指令

```powershell
python lotto.py watch                 # 常駐，每 300 秒
python lotto.py watch --once          # 只跑一輪
python lotto.py watch --interval 60   # 維運測試用
python automation_verify.py           # 後端、前端、鎖、故障恢復完整驗收
```
