# AI 辯論逐期信心校準預註冊

實驗版本：`debate-confidence-gating-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

先前 `debate-main-rank-calibration-audit-v1` 顯示辯論 top-10／20／30
整體沒有通過樣本外校準。本研究不再修改 cutoff，而是檢查辯論能否在
開獎前辨識「本期排名較可信」的條件：高信心期的 top-10／top-30 命中，
是否同時高於公平零模型與低信心期。

## 資料與時間界線

- 來源：`simulation/results/super.jsonl`、`simulation/results/lotto649.jsonl`。
- 統計粒度固定為每款遊戲每期一列，不把號碼或評論列當獨立樣本。
- 每期 feature builder 只能接收當期已封存 `decision`，不得接收
  `reveal`、實際號碼或事後 review。
- 每期必須有 15 個唯一 proposal、15 個一對一 candidate score、60 筆
  cross-agent critique、90 次合法主號出現及完整唯一的 38／49 號排名。
- 暖機 60 期；暖機後前 70% 為 development、最近 30% 為 holdout。
- 完整歷史已被先前研究使用，因此本研究屬嚴格受控探索；即使通過也只能
  建立不可回填的未來 shadow，不得宣稱歷史確認完成。

## 凍結信心分數

每期只計算兩個開獎前 component：

1. `support_margin`：完整號碼 support 排名第 1～10 名的平均
   `debate_support`，減去第 11～20 名平均。
2. `mean_candidate_disagreement`：15 個 adjudication candidate 的
   `disagreement` 平均。

每款遊戲只用 development 的平均與母體標準差作 z-score：

`confidence_index = (z(support_margin) - z(mean_candidate_disagreement)) / sqrt(2)`

兩項固定等權，不依 outcome 調權。Development 的線性插值第 25／75
百分位凍結為 low／high threshold；holdout 完全沿用，不重新分位。
`>= q75` 為 high、`<= q25` 為 low，其餘為 middle。

開獎前 profiling 顯示 `mean_critique_confidence` 的標準差僅約 `0.002`，
且含機械式固定席位，故預先排除以免 z-score 放大噪音。Proposal HHI 與
support margin 的 development 相關約 `0.65～0.71`，只作資料品質描述，
不重複加入 composite。

## 凍結 outcome 與零模型

兩款遊戲各檢查：

- `top_10_hits`
- `top_30_hits`

對每個 game／cutoff 固定兩個單尾假說：

1. high 信心期總命中是否高於單期
   `Hypergeometric(pool, cutoff, 6)` 完整 convolution。
2. high 平均命中是否高於 low 平均命中。零模型仍為兩組獨立的相同
   Hypergeometric；以完整離散分布枚舉
   `X_high / n_high - X_low / n_low`，不使用常態近似。

兩遊戲 × 兩 cutoff × 兩假說，共八個單尾精確 p 值使用同一個 Holm
family。另以 2,000 次、13 期 circular moving-block bootstrap 計算
high-vs-null 與 high-minus-low 95% 區間。

## 資料品質與漂移門檻

除來源 chronology、合法性、重複日期／期別與 ledger hash 外，必須同時
滿足：

- 所有 component 與 confidence index 有限且 development 標準差大於 0。
- 每個 holdout high／low 群至少占 15%，避免閾值漂移造成極小樣本。
- Holdout confidence index 平均的絕對值不超過 development 標準差單位
  `0.5`；超過時標示 distribution drift 並禁止候選。
- 每個 high／low 群在 holdout 前、後半皆非空。

## 候選門檻

某個 game／cutoff 只有以下全部成立，才可建立 future confidence-gated
shadow：

- Development 的 high-vs-null 與 high-minus-low 都大於 0。
- Holdout 對應的兩個 Holm p 都 `<0.05`。
- Holdout 兩個 13 期 block-bootstrap 95% 區間下界都大於 0。
- Holdout 前、後半的 high-vs-null 與 high-minus-low 都大於 0。
- 上述資料品質與漂移門檻全部通過。

任何通過結果都不得直接改正式號碼；未來 shadow 在 high 信心期沿用辯論
排名，其他期使用由 `experiment_id|game|date|period` SHA-256 固定的均勻
標籤排名，且只能從下一個尚未登記的新目標期開始。若四個
game／cutoff 都未通過，結論固定為停止新增歷史 confidence 假說，等待
既有不可回填前向資料。

## 防止過度解讀

- 不依 holdout 更換 component、權重、分位、cutoff 或 p 值方向。
- 不把 middle 群刪除後的較大差值冒充全期策略提升。
- 不把 confidence association 說成開獎因果機制。
- 不修改 `records/`、正式前向 ledger 或 7/20、7/21 已封存號碼。

本研究為純模擬；公平模型下每個合法號碼標籤的理論開出機率相同。

## 開封後方法 QA 修正

修正時間：`2026-07-19`，原始 holdout 結果開封後、正式驗收與策略決策前。

資料驗證發現：high／low 雖在每期開獎前決定，但 decision 會讀取過去歷史，
因此整段群組序列是 predictable adaptive assignment。把最後群組序列與
群組大小固定後使用 convolution，是有用的固定設計敏感度，卻不能單獨證明
自適應序列下的 type-I error。

因此新增更嚴格、不能救回候選的主要序列安全門檻：

- 單期命中 `X_t` 的公平條件分布仍為
  `Hypergeometric(pool, cutoff, 6)`，均值為 `mu`。
- High-vs-null 使用開獎前 predictable weight：
  high=`1`，其他=`0`。
- High-minus-low 使用 high=`+1`、low=`-1`、middle=`0`。
- 對固定正向 lambda grid
  `[0.05,0.10,0.20,0.40,0.80,1.60]`，逐期累積
  `exp(lambda*w_t*(X_t-mu)) / E0[exp(lambda*w_t*(X-mu))]`。
- 六個固定 betting martingale 等權混合成 e-value；
  anytime-valid p 為 `min(1, 1/e)`。
- 兩遊戲 × 兩 cutoff × 兩假說的八個 safe p 另用一個 Holm family。

候選除原門檻外，對應兩個 sequential-safe Holm p 也必須 `<0.05`。
原 convolution p 完整保留並標示為 fixed-realized-group sensitivity。
這項修正源自方法 QA，不改 feature、分位、方向、outcome 或既有失敗結果；
它只增加必要條件，不移除任何原失敗條件。
