# 跨遊戲前一期重複數完整子集合機率預註冊

實驗版本：`cross-game-overlap-subset-probability-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

現有研究已檢驗同一遊戲的球號頻率、星期、抽出順序、lag overlap 與轉移，
但尚未回答：在目標開獎前已揭曉的另一款遊戲最近一期，其共享號碼標籤與
目標六主號的重複個數，能否改善下一期完整無序六號集合機率？

本實驗只檢驗這一個低維條件訊號。不搜尋球號對球號轉移矩陣、日期窗口、
設備假說、月份、節日、lag 長度或兩款遊戲的不同 prior。

## 時間邊界與配對

- 目標遊戲為威力彩時，來源遊戲固定為大樂透；反之亦然。
- 對目標日期 `d`，來源期固定為日期嚴格小於 `d` 的最新一期。
- 來源與目標同日的結果一律不可使用，即使完整歷史中已知；模型仍使用更早
  的來源期。
- 若沒有任何嚴格較早的來源期，當期固定使用精確均勻分布，regret 為 0，
  且不更新跨遊戲 overlap state。
- 合法春節加開全部保留。多個目標期可以使用同一個當時最新的來源期；不得
  因事後知道下一個來源結果而重配。
- 第 `t` 期先 forecast、後 reveal、再更新；目標六主號不得影響當期 forecast。

日期配對盤點在查看 overlap 結果前固定為：

- 威力彩：1,929／1,929 期有嚴格較早的大樂透來源；42 個同日來源被忽略。
- 大樂透：2,042／2,153 期有嚴格較早的威力彩來源；前 111 期固定均勻；
  42 個同日來源被忽略。

## 唯一固定候選

比較：

1. `uniform`：每個合法無序六號集合機率 `1 / C(N,6)`。
2. `cross_game_overlap_dirichlet_null_1`：
   - 來源六主號中落在目標球池 `1..N` 的不同標籤集合記為 `B`，
     `m = |B|`。
   - 目標集合 `S` 的條件統計量固定為 `K = |S ∩ B|`。
   - 對每個目標遊戲及每個 `m=0,...,6` 維護獨立的七格
     `K=0,...,6` 歷史計數；不同 `m` 不混用。
   - 公平零模型的精確 overlap mass：

     `q_m(k) = C(m,k) C(N-m,6-k) / C(N,6)`。

   - 每個 `m` strata 使用固定總強度 1、中心為當期精確公平 mass 的
     Dirichlet-null predictive：

     `p_t(k|m) = (past_count_m(k) + q_m(k)) / (past_n_m + 1)`。

   - 完整集合機率：

     `P_t(S|B) = p_t(K|m) / [C(m,K) C(N-m,6-K)]`。

   - 同一 `m` 零歷史時，公式必須精確回到 `1/C(N,6)`。

這是一個完整正規化分布，不對重複格內的特定球號作任何偏好。威力彩來源
大樂透可能含 `39–49`，因此 `m` 可小於 6；大樂透來源威力彩的六號都在
`1–49`，所以有來源時固定 `m=6`。

禁止開封後：

- 改 Dirichlet 強度、合併或拆分 `m`／`K` 格。
- 改用同日來源、未來來源或日期最近但尚未揭曉的來源。
- 搜尋 lag-2、兩期聯集、球號轉移、正負相關方向或只挑某款遊戲。
- 排除春節加開、早期均勻期或表現較差的期間。
- 混入 Agent 分數、星期、抽出位置、第二區、特別號、銷售額或獎金。
- 用 top-k、票券命中、任一獎或 ordered sequence 取代完整 subset log loss。

## Proper score 與固定診斷

每期：

`regret_t = -log P_cross(S_t) - log C(N,6)`。

負值才代表候選比均勻基準給真正開出集合更高機率。每款遊戲固定輸出：

- 全期及有來源期平均 regret。
- 13 期 circular moving-block bootstrap、固定 seed、2,000 次 95% 區間。
- 前半、後半與最近 52／104／208 期平均 regret。
- 單期優於均勻比例。
- 最終及歷史最大 likelihood-ratio e-value。
- `m` strata 次數、七格 state、配對 lag 天數、同日忽略數、來源重用數與
  決定性 mapping／score／state hash。
- 無來源期最大絕對 regret 必須為 0。

正式浮點數正規化為 15 位有效十進位數。

## 決策門檻

歷史資料只作描述。只有兩款遊戲同時滿足全部條件，才允許另立 future-only
challenger：

1. 全期平均 regret `<0`。
2. bootstrap 95% 上界 `<0`。
3. 前半與後半平均 regret 都 `<=0`。
4. 最近 52／104／208 期平均 regret 全部 `<=0`。
5. 最終 e-value `>=60`。

任一條失敗：

- `future_challenger_design_allowed = false`
- 不新增 Agent、不接入 watcher。
- 維持 `uniform_null_safe`。
- 不修改既有前向登記或 records。

即使全部通過，也只能建立新的開獎前 future shadow；歷史不得直接 promotion。

## 必要驗收

1. 每個 `m=0,...,6` 零歷史時都精確均勻。
2. 小型球池枚舉全部合法六號集合，候選機率總和為 1。
3. 明確測試 strict-earlier、同日忽略、無來源均勻、來源重用與
   forecast-before-update。
4. raw／ledger 逐期一致、日期與期別唯一、號碼合法、records 不變。
5. 固定 bootstrap、mapping／state／score／artifact hash 決定性重現。
6. protocol、來源、配對、regret、排名或 decision 竄改 fail closed。
7. Python 3.11／3.12 位元級一致。
8. 專項、完整後端、前端、lint、production build、`git diff --check`
   全部通過。

本研究為純模擬，不構成購買或下注建議。
