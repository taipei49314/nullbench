# 跨遊戲最近一期 overlap 沒有提高完整六號機率

正式實驗：`cross-game-overlap-subset-probability-audit-v1`

## 結論

另一款遊戲最近已揭曉一期的共享號碼，沒有形成可延續的目標期機率訊號。
預註冊候選 `cross_game_overlap_dirichlet_null_1` 在兩款遊戲都輸給精確
均勻基準：

- 不新增跨遊戲 Agent 或 future challenger。
- 不接入 watcher。
- 不修改既有前向登記與 records。
- 機率決策維持 `uniform_null_safe`。

## 嚴格時間配對

每個目標只使用日期嚴格較早的另一款最新一期。同日另一款結果一律忽略：

| 目標遊戲 | 目標期 | 有嚴格較早來源 | 無來源 | 同日來源忽略 |
|---|---:|---:|---:|---:|
| 威力彩 | 1,929 | 1,929 | 0 | 42 |
| 大樂透 | 2,153 | 2,042 | 111 | 42 |

威力彩來源 lag 為 1–3 天；大樂透為 1–4 天。大樂透早於威力彩上市的前
111 期固定均勻。春節加開造成多個目標共用同一個當時最新來源時，依真實
可用狀態保留，不以未來來源重配。

## 固定完整機率模型

- 來源六號中落在目標球池的集合大小為 `m`。
- 目標與來源共享標籤的重複數為 `K`。
- 每個 `m=0..6` 獨立維護 `K=0..6` 的累積計數。
- prior 總強度固定為 1，中心是精確公平超幾何分布
  `C(m,K)C(N-m,6-K)/C(N,6)`。
- 每個 overlap 格的 predictive mass 均分給該格全部合法完整六號集合。
- 同一 `m` 零歷史時精確回到 `1/C(N,6)`。
- 不估球號轉移矩陣，不搜尋 lag、窗口、方向或 prior。

## Proper-score 結果

Regret 是候選完整 subset log loss 減精確均勻基準；負值才是提高機率。

| 指標 | 威力彩 | 大樂透 |
|---|---:|---:|
| 全期平均 regret | +0.023937918 | +0.008117051 |
| 有來源期平均 regret | +0.023937918 | +0.008558281 |
| 13 期 block-bootstrap 95% | `[+0.011440185,+0.038322264]` | `[+0.001407746,+0.017176250]` |
| 前半平均 regret | +0.034675898 | +0.010040974 |
| 後半平均 regret | +0.013211065 | +0.006194914 |
| 最近 52 期 | +0.007878617 | +0.000081729 |
| 最近 104 期 | +0.005055227 | +0.000438824 |
| 最近 208 期 | -0.000082885 | +0.001308097 |
| 單期優於均勻比例 | 51.3219% | 47.9796% |
| 最終 e-value | `8.83e-21` | `2.57e-08` |

威力彩雖有略多於一半期數的單期 regret 為負，但較差期的損失幅度更大；
proper score 不能用勝率取代。兩個 bootstrap 下界都大於零、前後半皆為正，
且最終 e-value 遠低於 60。

候選對真正開出集合的幾何平均機率只有均勻基準的：

- 威力彩：`97.6346%`
- 大樂透：`99.1916%`

## 完整性與驗收

- 494 份官方 raw 月檔、4,082 期，與 replay ledger 逐期零不符。
- 同日 42／42 個來源全部按規則忽略。
- 無來源期最大絕對 regret 為 0。
- mapping、score trace、各 `m` state 均有決定性 hash。
- 專項數學、日期、live recompute 與竄改測試：38／38。
- Python 3.11／3.12 正式 JSON 位元級相同。
- `records/` 維持
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

正式產物：

- `research/results/cross_game_overlap_signal.json`
- artifact SHA-256：
  `32545dd82e1752c114d23b6b26bb62ae8952a466b0a39ef8d069812e5dd7a76b`
- audit hash：
  `b138216bd78c9d8b9f99288b8d3a4b248aa25f0fdceda81a531c2cda79979f3a`
- protocol file SHA-256：
  `f63b7ad473503c4abdac6cf57aa262dd3852f7a285157d0acd0341f877c990c7`
- protocol payload hash：
  `6ce32454e866512d31ff79cd005e96489f0a14b7fd2311663370e0d3dd0d266c`

```powershell
python -B -X utf8 cross_game_overlap_signal.py
python -B -X utf8 cross_game_overlap_signal_verify.py --tests-only
```

本研究為純模擬，不構成購買或下注建議。
