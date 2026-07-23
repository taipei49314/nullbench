# 持續球號偏差完整子集合機率預註冊

實驗版本：`persistent-label-bias-subset-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

既有 `draw-mechanism-signal-audit-v1` 已檢查歷史頻率排名選出的 30 個主號，
能否在巢狀 holdout 增加實際涵蓋命中；結果未通過。它沒有回答另一個更直接的
機率問題：若每個球號真的存在跨期持續的微小物理偏差，使用截至上一期的全部
出現次數，能否提高下一期「完整無序六號子集合」的 proper-score 機率？

本實驗只補這個缺口。排名命中、最佳一注命中或 30 號聯集命中都不能替代完整
子集合 log loss。

## 資料、時間順序與品質

- 威力彩：`records/super.jsonl`，主號定義域 `1–38`。
- 大樂透：`records/lotto649.jsonl`，主號定義域 `1–49`。
- 每款遊戲每期恰有六個不同主號；第二區與特別號不在本實驗範圍。
- 必須通過正式 ledger 雜湊鏈、日期遞增、期別唯一、號碼範圍與每期六個不同
  主號檢查。
- 第 `t` 期 forecast 只能讀取第 `t-1` 期以前的主號。第 `t` 期揭曉後才更新
  累積次數，供第 `t+1` 期使用。
- 春節加開與其他合法期數依實際日期順序保留，不刪期、不插補。

任一資料品質或時間順序條件失敗，整個研究 fail-closed。

## 唯一固定候選

只比較兩個模型，不搜尋參數：

1. `uniform`：每個合法無序六號子集合機率固定為 `1 / C(N, 6)`。
2. `persistent_dirichlet_1`：
   - 每個球號 `i` 在 forecast 前的權重固定為
     `w_i = past_occurrence_count_i + 1`。
   - `+1` 是預先固定的對稱 Laplace／Dirichlet prior；不得在看結果後修改。
   - 依六個位置順序，以目前剩餘球號的正權重做無放回抽樣。
   - 目標無序六號集合的機率，以 64-state subset dynamic programming
     精確加總該集合全部 `6! = 720` 個抽出順序。

零歷史時所有權重相同，模型必須精確回到 `1 / C(N, 6)`。模型只有 `N` 個
累積計數，不拆六個抽出位置，也不使用當期抽出順序。

禁止在結果揭曉後：

- 改 prior、增加 shrinkage 或改成 empirical-Bayes 調參。
- 加 rolling、EWMA、星期、期號、lag、gap、冷熱窗口或設備年代切點。
- 混入 Agent 辯論分數、第二區、特別號、銷售額或獎金欄位。
- 只挑某款遊戲、某段期間或某些球號。
- 以 ordered-sequence loss、top-k 命中或票券命中取代完整 subset proper score。

## Proper score 與固定診斷

每期定義：

`regret_t = -log P_persistent(S_t) - log C(N, 6)`

負值才代表候選對完整六號集合給出比精確均勻基準更好的機率。每款遊戲固定
輸出：

- 全期平均 regret。
- 13 期 circular moving-block bootstrap、2,000 次抽樣的 95% 區間。
- 前半與後半平均 regret。
- 最近 52、104、208 期平均 regret。
- 單期 regret 小於零的比例。
- 累積 likelihood ratio 的最終與歷史最大 e-value。
- 最終每個球號累積次數與 state hash。

bootstrap 與任何隨機診斷使用固定 seed；輸出數字統一正規化為 15 位有效
十進位數，確保 Python 版本間正式 artifact hash 一致。

## 決策門檻

歷史結果一律只作描述，不得直接升級正式號碼。只有兩款遊戲同時滿足以下全部
條件，才允許另立新的 future-only challenger：

1. 全期平均 regret `< 0`。
2. 95% block-bootstrap 上界 `< 0`。
3. 前半與後半平均 regret 都 `<= 0`。
4. 最近 52、104、208 期平均 regret 全部 `<= 0`。
5. 最終 e-value `>= 60`。

任一條失敗：

- `future_challenger_design_allowed = false`
- 不新增 Agent。
- 不接入 watcher。
- 維持現行 `null-safe-probability-forward-shadow-v1`。
- 不修改既有 2026-07-20、2026-07-21 或其他已封存前向號碼。

即使全部通過，也只能封存一個新的未來實驗；歷史資料不得成為正式 promotion
證據。

## 必要驗收

1. 零歷史時兩款遊戲都精確等於 `1 / C(N, 6)`。
2. 小型球池以全部 `6!` 排列窮舉驗證 DP，且全部合法子集合機率總和為 1。
3. 明確測試 forecast-before-update，當期 reveal 不得影響當期機率。
4. 資料品質、ledger、period/date 順序與 records 不變性測試。
5. 固定 bootstrap／hash 重現性與跨 Python 版本一致性。
6. regret、raw source、protocol、決策或 promotion 欄位竄改必須 fail-closed。
7. targeted tests、正式 verifier、完整後端回歸、前端測試／lint／build 全部
   通過後才結束本階段。

本研究為純模擬，不構成購買或下注建議。
