# 桌機背景 Loop 規格

## 目標

只要 `npm run dev` 的桌機伺服器仍在，關閉瀏覽器分頁也要每五分鐘完成一次：

1. 比對台彩官方當月資料。
2. 有新開獎才重建逐期 Agent 回放與 Qwen 終局裁決。
3. 只結算已在開獎前凍結的 Qwen／規則／均勻隨機三臂。
4. 凍結新的下一期三臂，更新前端可讀摘要。

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

## 指令

```powershell
python lotto.py watch                 # 常駐，每 300 秒
python lotto.py watch --once          # 只跑一輪
python lotto.py watch --interval 60   # 維運測試用
python automation_verify.py           # 後端、前端、鎖、故障恢復完整驗收
```
