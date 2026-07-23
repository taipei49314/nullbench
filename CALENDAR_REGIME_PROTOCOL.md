# 開獎星期完整子集合機率預註冊

實驗版本：`calendar-weekday-subset-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題與既有證據

`draw-mechanism-signal-audit-v1` 已用巢狀時間 holdout 檢驗星期分組的前 30
個主號能否增加六號涵蓋數；威力彩 holdout 差為 `+0.0439`，但區間跨零，
大樂透 holdout 差為 `-0.0493`。該研究不能回答星期條件分布能否改善
「下一期完整無序六號集合」的機率。

本實驗只補這個 proper-score 缺口。不得再搜尋月份、節日、農曆日期、期號、
月份內位置或星期交互作用。

## 資料、排程與時間順序

- 威力彩：`records/super.jsonl`，主號 `1–38`，正常開獎日為週一、週四。
- 大樂透：`records/lotto649.jsonl`，主號 `1–49`，正常開獎日為週二、週五。
- 官方 raw 月檔必須與正式 replay ledger 逐期一致。
- 第 `t` 期 forecast 只能讀取第 `t-1` 期以前的主號及日期；當期日期屬排程
  資訊，可在開獎前使用。
- 第 `t` 期開出後才更新其星期計數，供後續相同星期使用。
- 威力彩歷史 1,929 期皆在正常星期。大樂透 2,153 期中 2,040 期在正常
  星期，113 期為合法春節加開。
- 春節加開保留在評分序列，但候選必須對任何正常星期外日期回到精確均勻
  分布；不得為稀疏的加開星期另建模型。

任一日期、期別、號碼範圍、每期六個不同主號、ledger 雜湊鏈或 raw 對照
失敗，研究 fail-closed。

## 唯一固定候選

只比較兩個模型，不搜尋參數：

1. `uniform`：每個合法無序六號子集合機率固定為 `1 / C(N, 6)`。
2. `weekday_dirichlet_1_regular`：
   - 正常開獎日的球號 `i` 權重固定為
     `w_i = past_same_weekday_occurrence_count_i + 1`。
   - `+1` 是預先固定的對稱 Laplace／Dirichlet prior。
   - 六次抽取均在剩餘球號中依同一組正權重做無放回抽樣。
   - 目標無序六號集合機率，以 64-state subset dynamic programming
     精確加總全部 `6! = 720` 個抽出順序。
   - 正常星期外日期直接輸出精確均勻機率，但開出後不更新任何正常星期模型。

同星期零歷史時，候選必須精確回到 `1 / C(N, 6)`。

禁止在結果揭曉後：

- 修改 prior、加入 shrinkage、rolling、EWMA 或全域頻率 fallback。
- 新增月份、節日、期號、季節、lag、gap、冷熱窗口或設備年代切點。
- 排除春節加開、只挑某個星期、某款遊戲、某段期間或某些球號。
- 混入 Agent 辯論分數、第二區、特別號、銷售額或獎金欄位。
- 以 ordered-sequence loss、top-k、30 號涵蓋率或票券命中取代完整 subset
  proper score。

## Proper score 與固定診斷

每期：

`regret_t = -log P_weekday(S_t) - log C(N, 6)`

負值才代表候選比精確均勻基準給真正開出集合更高的機率。每款遊戲固定輸出：

- 全期平均 regret。
- 13 期 circular moving-block bootstrap、固定 seed、2,000 次抽樣的 95%
  區間。
- 前半與後半平均 regret。
- 最近 52、104、208 期平均 regret。
- 單期 regret 小於零的比例。
- 累積 likelihood ratio 的最終與歷史最大 e-value。
- 各正常星期的期數、最終球號計數與 state hash。
- 正常星期外期數及其 regret 必須精確為零。

正式數值統一正規化為 15 位有效十進位數，以維持跨 Python 版本 artifact
重現性。

## 決策門檻

歷史資料只作描述，不得直接升級正式號碼。只有兩款遊戲同時滿足全部條件，
才允許另立新的 future-only challenger：

1. 全期平均 regret `< 0`。
2. 95% block-bootstrap 上界 `< 0`。
3. 前半與後半平均 regret 都 `<= 0`。
4. 最近 52、104、208 期平均 regret 全部 `<= 0`。
5. 最終 e-value `>= 60`。

任一條失敗：

- `future_challenger_design_allowed = false`
- 不新增 Agent、不接入 watcher。
- 維持 `uniform_null_safe` 為機率決策。
- 不修改既有 2026-07-20、2026-07-21 或其他已封存前向號碼。

即使全部通過，也只能建立新的未來預註冊實驗；歷史資料不得作正式 promotion
證據。

## 必要驗收

1. 同星期零歷史與正常星期外日期皆精確等於 `1 / C(N, 6)`。
2. 小型球池以全部 720 條路徑及全部合法六號子集合驗證 DP 與機率總和。
3. 明確測試 forecast-before-update、星期 state 隔離及春節加開不污染 state。
4. 資料品質、排程、ledger、raw 對照與 `records/` 不變性測試。
5. 固定 bootstrap、state hash、artifact hash 與跨 Python 版本重現性。
6. source、protocol、regret、decision 或 promotion 欄位竄改必須 fail-closed。
7. targeted tests、正式 verifier、完整後端回歸、前端 tests／lint／build 全部
   通過後才結束本階段。

本研究為純模擬，不構成購買或下注建議。
