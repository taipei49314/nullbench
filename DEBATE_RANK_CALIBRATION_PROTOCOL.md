# AI 辯論主號排名校準預註冊

實驗版本：`debate-main-rank-calibration-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

每期開獎前，15 組 Agent 提案與 60 次交叉評論會形成完整主號支持排名。
目前 `guarded_profit` 把前 10 名映射到二重 membership、前 11～20 名映射
到單一 membership；`unconstrained_profit` 把前 10 名映射到三重
membership。本研究檢查這個排名是否真的和下一期開出主號有樣本外關係。

## 資料與時間界線

- 來源：`simulation/results/super.jsonl`、`simulation/results/lotto649.jsonl`。
- 粒度：每款遊戲每期一列。
- 每期排名只能由該期已封存的 `decision.proposals` 與
  `decision.adjudication.candidate_scores` 重建；函式不得接收 `reveal`。
- 每期必須有 15 個唯一 proposal、15 個對應 debate score，並形成涵蓋整個
  號碼池的唯一完整排名。
- 暖機 60 期；暖機後前 70% 為 development、最近 30% 為 holdout。
- Development 只用於方向穩定性；所有確認性 p 值與區間只用 holdout。

## 預註冊指標

兩款遊戲分別計算：

1. `top_10_hits`：實際六主號落在排名前 10 名的數量。
2. `top_20_hits`：實際六主號落在排名前 20 名的數量。
3. `top_30_hits`：實際六主號落在排名前 30 名的數量。
4. `top_10_minus_next_10_hits`：前 10 名命中數減去第 11～20 名命中數。

前三項的單期公平零模型是 `Hypergeometric(pool, cutoff, 6)`；跨期總命中
使用完整 convolution，不使用常態近似。每款遊戲三項、共六項雙尾精確 p
共用一個 Holm family。第四項使用 13 期 moving-block bootstrap 95% 區間，
專門檢查 guarded 中前 10 名獲得較高 multiplicity 是否有資料支持。

## 方向與決策門檻

`top_10` 正向校準只有在以下條件全通過時成立：

- Development 平均差相對精確零模型大於 0。
- Holdout Holm p `<0.05`。
- Holdout 13 期 block-bootstrap 區間下界大於 0。
- Holdout 前後半平均差皆大於 0。

負向校準使用完全對稱門檻：development 小於 0、Holm p `<0.05`、區間上界
小於 0、前後半皆小於 0。`top_20`、`top_30` 使用同一規則。

高 multiplicity 映射另要求：

- Unconstrained：威力彩 `top_10` 通過正向校準。
- Guarded：威力彩 `top_10` 通過正向校準，且
  `top_10_minus_next_10_hits` 的 development、holdout 前後半皆為正，
  block-bootstrap 區間下界大於 0。

若威力彩 `top_10` 通過負向校準，才可建立「反向映射」的獨立未來 shadow；
不得直接改現行結構。若正負都未通過，維持現行映射作確定性 tie-break，
但禁止宣稱辯論高支持號碼較可能開出。

## 防止過度解讀

- 不依 holdout 改 cutoff、score 公式或 tie-break。
- 不把 38／49 個號碼－期別列當成彼此獨立樣本；統計單位固定為一期。
- 不以單一遊戲或單一 cutoff 的未校正 p 宣稱成功。
- 完整歷史已被先前研究使用；即使通過也只能建立未來不可回填 shadow。
- 本研究不得修改 `records/`、正式前向 ledger 或既有號碼。

本研究為純模擬；公平模型下每個合法號碼標籤的理論開出機率相同。
