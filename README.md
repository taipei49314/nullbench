# lotto-lab — 虛擬彩票研究室（純模擬，不下注）

> **本系統為負期望值之純模擬實驗，統計上每期獨立。**
> 它不預言號碼；它的正式問題是：「任何選號策略的長期績效，是否顯著異於純隨機？」
> 預期（且樂見）的答案是否——詳見 [PREREG.md](PREREG.md)。

架構承 `ai-company` 紀律：董事會辯論 → 裁決規格 → 測試先行 → 決定性種子 →
append-only 帳本（雜湊鏈）→ null model 併跑 → 繁中報告（結論先行）。
純 Python stdlib，資料來自台彩官方 API（威力彩 2008-01 起、大樂透 2007-01 起全歷史）。

## 桌機戰情室

酷炫前端會直接讀取 `simulation/results/` 的真實逐期辯論、裁決與檢討資料，不使用假資料。
畫面專為 1180px 以上桌機瀏覽器設計：

```powershell
python lotto.py loop
cd frontend
npm install
npm run dev
```

開啟 `http://127.0.0.1:5173/`。前端品質檢查可用：

```powershell
npm run lint
npm run test
npm run build
```

## 每週流程（全部手動觸發，零排程零推播）

```
python lotto.py picks    # 週末/週一開獎前：辯論＋兩遊戲各 5 組＋凍結預註冊
python lotto.py check    # 該週開獎完（建議週六）：抓新開獎→結算→權重更新→產報告
python lotto.py report   # 重新產報告；python lotto.py status 看總覽
python lotto.py ingest   # 手動更新歷史資料（check 會自動做）
python lotto.py loop     # 逐期 agent 辯論閉環：完整歷史回放＋下一期模擬號碼
```

## 逐期 agent 自動閉環（純模擬）

`python lotto.py loop` 會對威力彩與大樂透分別從第一筆歷史資料開始，逐期執行：

1. 嚴格切出目標期以前的歷史，目標期號碼不進入決策。
2. 五個 agent 各提出 3 組候選，共 15 組。
3. 每個 agent 評議其他四位的候選，共 60 筆交叉評議。
4. 裁決器依既有可信度、評議分數、號碼重疊與單一 agent 集中度選出 5 注。
5. 揭曉該期實際結果，量化漏號、重複押錯、未入選提案的事後表現與各 agent 成績。
6. 揭曉後才更新可信度，更新狀態只會影響下一期。

逐期決策、辯論、揭曉與檢討會寫入 `simulation/results/<game>.jsonl`。每行含前一行雜湊、
決策雜湊與檢討雜湊，可驗證沒有事後改號；再次執行會從頭決定性重建，不沿用不可稽核的
可變狀態。完整正式驗證使用：

```
python agent_loop_verify.py
```

「最有可能」在此只表示 agent 辯論後的相對排序，不代表合法組合的理論開出機率不同。
本地 Ollama 可協助生成文字評論，但不進入全歷史選號裁決，以維持離線可跑與位元級重現。

## 全歷史策略研究（與正式 v1 隔離）

```
python research_verify.py     # 建議：四階段測試 → 正式回測 → 全套驗收
python research_backtest.py   # 只重跑正式研究
```

研究管線會逐週回放全部官方歷史，只允許使用當週以前的資料。前 50% 週用於
粗搜尋與局部細調，接續 25% 用於選擇五注政策，最後 25% 是一次性封存測試集。
結果寫到 `research/results/`，不會讀寫 `records/`，也不會改動已凍結的 v1 票。

「最佳決策」分成兩層：經濟層以不參與為基準；條件式研究層則比較固定模擬
五注時的政策。只有封存測試集相對純隨機的區間、一致性與固定獎級護欄全部
通過，才允許替換條件式 `random_5` 基準。

## 五個選號人格（每遊戲每週 5 席）

| 人格 | 席位 | 手法 |
|------|------|------|
| 亂數修士 | 保留第 1 席、權重凍結 | 純均勻隨機——內建活體對照 |
| 熱手獵人 | 權重競爭 | 近 50 期指數衰減頻率加權 |
| 冷灶守望者 | 權重競爭 | 遺漏值加權（賭徒謬誤的忠實代表，收進來就是為了檢驗它） |
| 均衡工程師 | 權重競爭 | 拒絕取樣：和值帶/奇偶/連號/尾數/極差五約束 |
| 反眾道人 | 權重競爭 | 避開生日號碼帶——唯一有理論依據（不改機率、只影響同額分彩） |

每週核對後，各人格的**影子票**成績對 1,000 注 null 票取百分位排名，
乘法權重更新（η=0.10、均勻混合 ε=0.10、clamp [0.05,0.60]、前 8 週 burn-in 凍結）。
權重是**被研究的展品，不是引擎**——理論預期它長期隨機漫步。

## 誠實設計（裁決書 honesty guards）

- **200 組 null 對照**與正式組同種子紀律、同估值、同一條結算程式路徑。
- 出號**凍結預註冊**（content_hash＋code_hash），開獎前落檔，逾時標 LATE 不入正式統計。
- 核對前**種子重放驗證**，號碼不符整週 INVALID。
- 浮動獎金**反事實保守估值**（我們若真中會多一個分獎人），固定/浮動雙帳本永不合併。
- 報告產生器內建**禁用詞 lint**（預測/必中/即將開出/勝率提升/破解 → 拒絕產檔）。
- 本地 Ollama qwen3:8b 是**評論席**：只評論、永不產號、離線自動降級模板。

## 檔案地圖

```
lotto.py              CLI
engine/
  games.py            獎則引擎（獎級判定＋保守估值）
  fetch.py            台彩官方 API 逐月抓取＋不可變快取
  store.py            開獎庫＋ISO 週時間學
  analysts.py         五人格（決定性產號）
  picker.py           席位分配＋出號＋凍結預註冊＋null 票
  settle.py           每週核對（重放驗證→逐期結算→週結→權重）
  strategy.py         權重 replay/更新（無可變狀態檔）
  report.py           繁中週報（結論先行＋lint）
  debate.py           董事會陳述＋AI 評論席
  ledger.py           append-only JSONL（SHA-256 雜湊鏈）
  seeds.py / config.py / stats.py / env.py / ollama_seat.py
data/raw/<game>/      官方 API 原始月回應（估值永遠可離線重放）
records/              picks / settlements / weights / commentary 帳本＋reports/
research/             全歷史走步回測、兩階段搜尋與封存外驗
output/jupyter-notebook/
                      可重跑的策略研究伴隨筆記本
tests/                研究與正式流程完整測試
```

## 驗證紀律

改任何 engine 邏輯後：`python -X utf8 -m pytest tests -q` 必須全綠。
正式策略研究使用 `python research_verify.py`；資料品質、策略搜尋、
validation/holdout 與決策報告四個階段任一測試或閘門失敗都會立即停止。
改參數＝開新 experiment_id（見 PREREG.md），禁止原地調參沿用舊帳。
