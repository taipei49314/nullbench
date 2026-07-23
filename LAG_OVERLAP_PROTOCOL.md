# 相鄰期重複數完整子集合機率稽核契約

版本：`lag-overlap-subset-probability-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 決策問題

上一期與下一期六主號的重複個數，是否具有能提高下一期完整無序六號集合機率的
可預測偏差？

既有 `draw-mechanism-signal-audit-v1` 已檢查相鄰期重複數的整體分布，
`lag-transition-signal-audit-v1` 已檢查高維號碼轉移的 top-30／五注命中；
兩者都沒有確認訊號。但它們都沒有對全部合法六號集合建立正規化分布並以
proper score 評分。本實驗只補這個量尺缺口，不搜尋號碼、窗口或轉移矩陣。

## 資料與 grain

- 遊戲：威力彩主號、大樂透主號。
- 一列：一款遊戲的一個正式期別。
- 主鍵：`game + period`；日期必須嚴格遞增。
- 威力彩使用 1,929 期，大樂透使用 2,153 期的完整正式歷史。
- raw API 與 replay ledger 的期數、日期、主號集合與 hash 必須逐期一致。
- 任何重複期別、重複日期、非法主號、缺值或 raw／ledger 不符都 fail closed。

欄位分類固定為：

- `period`、`lotteryDate`：開獎前排程可知，只作身份與時間順序。
- 上一期 `drawNumberSize[:6]`：已揭曉的歷史，只用來建立下一期重複集合。
- 當期 `drawNumberSize[:6]`：開獎後才可知，只作 proper-score target，評分後
  才更新 state。
- 抽出順序、第二區／特別號、銷售額、獎金與派彩：全部排除。

## 精確均勻基準

球池大小為 `N`，每期取六個主號。令當期集合與上一期集合的交集大小為
`K ∈ {0,...,6}`。公平、獨立開獎下：

`p0(K=k) = C(6,k) × C(N-6,6-k) / C(N,6)`

具有相同 `k` 的合法六號集合數為：

`M(k) = C(6,k) × C(N-6,6-k)`

因此每個合法六號集合的基準機率都是 `1 / C(N,6)`。

## 唯一固定候選

候選 ID：`lag_overlap_dirichlet_null_1`

候選只維護先前相鄰期轉移的七格重複數計數 `n_k`。Dirichlet prior 固定為：

`alpha_k = p0(K=k)`

所以 prior 總強度恰為一個虛擬轉移，prior predictive 精確等於公平零模型。
不另選 Laplace 強度、不依遊戲調參、不設 rolling window。

對第 `t >= 2` 期，在讀取當期開獎前：

`q_t(k) = (n_{t-1,k} + alpha_k) / (sum_j n_{t-1,j} + 1)`

任一與上一期重複 `k` 個號碼的完整六號集合機率為：

`P_t(S) = q_t(k) / M(k)`

這對全部 `C(N,6)` 合法集合形成嚴格正值、總和為一的分布。第一期沒有上一期，
固定使用精確均勻分布，regret 為零。

## Prequential 順序與計分

每一期固定依序：

1. 只讀截至上一期 reveal 的 `n_k` 與上一期集合。
2. 建立當期 `q_t` 與完整六號分布。
3. 才讀取當期 reveal，計算 `k` 與分數。
4. 最後把當期 transition 更新到 `n_k`，供下一期使用。

原始候選每期 likelihood ratio：

`LR_t = q_t(k_t) / p0(k_t)`

原始 regret：

`regret_t = -log(LR_t)`

負 regret 才代表候選給實際開獎集合的機率高於精確均勻。正式摘要保存平均
regret、資訊增益、幾何平均機率倍數、前後半、最近 52／104／208 期與
13 期 circular moving-block bootstrap 95% 區間；bootstrap 固定 2,000 次，
seed 由 experiment ID、game 與 metric 決定。

## Null-safe gate

原始候選的累積 e-process：

`E_t = product_{i=2..t} LR_i`

在公平、獨立的精確零模型下，這是以開獎前 predictive density 建立的非負
martingale。兩款遊戲共用 family alpha `0.05`，每款固定 alpha `0.025`，
所以啟用門檻為 `E >= 40`。

安全 forecast 在第 `t` 期只能讀 `E_{t-1}`：

- `E_{t-1} < 40`：完整六號機率精確均勻。
- `E_{t-1} >= 40`：使用 `lag_overlap_dirichlet_null_1`。

當期 reveal 只能更新第 `t+1` 期 gate。保存每期 prior e-value、是否啟用、
raw regret 與 safe regret 的 trace hash，不輸出逐期開獎號碼。

## 固定決策門檻

只有兩款遊戲都同時滿足下列五項，才允許另立 future-only challenger：

1. 原始平均 regret `< 0`。
2. 原始 13 期 block-bootstrap 95% 上界 `< 0`。
3. 前半與後半平均 regret 都 `<= 0`。
4. 最近 52、104、208 期平均 regret 全部 `<= 0`。
5. 最終 `E >= 40`，即下一個目標期的 gate 為 active。

歷史結果永遠不得直接 promotion；`historical_promotion_eligible` 與
`watcher_integration_allowed` 固定為 `false`。即使五項通過，也只能建立新的
開獎前、不可回填 future experiment。未通過則維持既有 null-safe。

本候選不論結果好壞，都必須在後續 `main-subset-probability-frontier-v2`
以相同完整 subset regret 加入一列；v1 artifact 不得改寫。

## 完整性與測試

1. protocol 檔 SHA-256、protocol payload hash、raw tree hash、ledger hash、
   score trace hash、state hash、artifact hash 全部固定保存。
2. `sum_k p0(k)` 與每一期 `sum_k q_t(k)` 必須在浮點容許度內等於一。
3. 全零 state 的 predictive 必須逐格等於 `p0(k)`。
4. 人工資料必須驗證先 forecast、後 reveal 更新，且重跑完全決定性。
5. 欄位、regret、e-value、gate timing、bootstrap、結論、records hash 或
   artifact hash 任一竄改必須 fail closed。
6. Python 3.11／3.12 正式 artifact 必須位元級一致。
7. 專項測試、完整後端、前端測試、lint、production build 與
   `git diff --check` 必須通過。
8. `records/`、Agent、既有 7/20／7/21 登記與 watcher 不得由本研究修改。

本研究為純模擬，不構成購買或下注建議。
