# 抽出順序子集合訊號預註冊

實驗版本：`draw-order-subset-signal-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

官方原始 API 同時保存排序後號碼 `drawNumberSize` 與實際抽出順序
`drawNumberAppear`。現行正式 ledger 只保存排序後六個主號，因此既有
Agent、機制訊號與 probability stacking 都沒有使用抽出位置。

本實驗只回答一個問題：過去各抽出位置的號碼分布，能否在嚴格不讀取當期
結果的條件下，提高下一期「完整無序六號子集合」的 proper-score 機率？
只改善抽出順序本身不算成功；玩家投注不含主號順序。

## 原始資料與欄位資格

- 威力彩來源：`data/raw/super/*.json`。
- 大樂透來源：`data/raw/lotto649/*.json`。
- 研究粒度：每款遊戲每期一列。
- `drawNumberAppear[:6]` 是六個主號的抽出順序；
  `drawNumberAppear[6]` 是威力彩第二區或大樂透特別號。
- 當期 `drawNumberAppear`、`drawNumberSize`、銷售額、獎金池、中獎人數、
  單注獎金與兌獎日全部是結果後欄位，禁止供當期 forecast 使用。
- 唯一新增特徵是「目標期以前」的 `drawNumberAppear[:6]`。
- 期號與預定日期雖可在開獎前知道，但沒有新增號碼資訊，本實驗不使用。
- `sellAmount` 是否能在開獎前可靠取得沒有正式 timestamp 證明，fail-closed
  排除。

資料品質必須同時滿足：

1. 所有 JSON 可解析，root 與 row schema 完整。
2. 每列兩個號碼陣列皆恰為 7 碼。
3. 前六碼各自不重複、範圍合法，且兩陣列前六碼集合相同。
4. 第七碼相同且符合各遊戲規則。
5. 期號唯一、日期月份與檔名一致、`totalSize` 等於列數。
6. 原始排序號碼必須逐期與正式 replay ledger 完全相符。
7. `drawNumberAppear` 有效覆蓋率必須為 100%。

任一條件失敗，研究整體 fail-closed，不插補、不刪期。

## 唯一固定模型

只比較兩個模型，不作參數搜尋：

1. `uniform`：所有合法無序六號子集合機率皆為 `1 / C(N, 6)`。
2. `position_dirichlet_1`：六個抽出位置各自維護每個球號的累積次數，
   使用固定 Laplace prior `alpha = 1`。

第 `t` 期 forecast 僅使用第 `t-1` 期以前的計數。模型依六個位置順序、
每次在剩餘球中按該位置的正值權重做無放回抽樣。目標無序子集合的機率
不是用觀察到的單一順序代替，而是以 64-state subset dynamic programming
精確加總該六碼的全部 `6!` 個合法抽出順序。當期揭曉後才更新六個位置
計數，供下一期使用。

禁止在看結果後：

- 改 `alpha`。
- 加 rolling、EWMA、星期、期號、銷售額或獎金欄位。
- 只挑某一抽出位置或某一款遊戲。
- 用 ordered sequence log loss 取代完整無序子集合 proper score。

## Proper score 與診斷

每款遊戲逐期計算：

`regret_t = -log P_position(S_t) - log C(N, 6)`

負值才代表位置模型優於精確均勻子集合機率。固定輸出：

- 全期平均 regret。
- 13 期 circular moving-block bootstrap、2,000 次抽樣的 95% 區間。
- 前半與後半平均 regret。
- 最近 52、104、208 期平均 regret。
- 單期優於均勻的比例。
- 累積 likelihood ratio 的最終與歷史最大 e-value。
- 最終每個位置的號碼計數與模型 state hash。

另作一項描述性 ordering 診斷：在固定每期六號集合下隨機排列位置，檢查
實際位置－球號關聯是否超過條件隨機排列；它不能取代子集合 proper score
或單獨觸發升級。

## 固定決策規則

歷史資料已被其他研究使用，因此永遠不得直接升級。只有在兩款遊戲同時
符合以下全部條件時，才允許建立全新的、不可回填 future-only challenger：

- 全期平均 regret 小於 0。
- bootstrap 95% 上界小於 0。
- 前半與後半平均 regret皆不大於 0。
- 最近 52、104、208 期平均 regret皆不大於 0。
- 最終 e-value 皆至少達兩 stream family-wise 門檻 `40`。

否則結論固定為 `retain_existing_null_safe_protocol`，不新增 Agent、不改
既有號碼、不接入 watcher。

即使歷史條件全數通過，future-only challenger 仍從 e-value `1` 開始，
兩款遊戲都達 `40` 前只能作 shadow；不得消費本次歷史 likelihood ratio。

## 完整性與不可變性

- 結果必須保存 protocol file SHA-256、494 份 raw snapshot hash、兩份
  replay ledger hash、records 前後 hash 與 audit hash。
- 正式輸出必須恰有兩個遊戲結果，且所有有限值、日期、期數、state hash
  可由來源重建。
- 浮點摘要在進入 audit hash 前固定為 15 位有效數字，避免 Python 版本間
  單一 ULP 差異破壞同資料、同演算法的重算一致性。
- 本研究不得修改 `records/`、simulation ledger、前向登記、null-safe
  operational state 或既有候選號碼。

本研究為純模擬。公平開獎下所有合法號碼組合理論等機率，不構成購買或
下注建議。
