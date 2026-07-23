# AI 辯論逐期信心校準

實驗版本：`debate-confidence-gating-audit-v1`

## 結論

辯論無法可靠辨識「本期排名比較可信」。威力彩高信心期的 top-10 與
top-30 都低於公平零模型；大樂透 holdout 雖略為正，但 development
方向不一致、區間跨 0、精確 p 值未通過八項 Holm，top-30 前半也反向。

不建立 confidence-gated shadow，不修改正式號碼，並停止再用同一份完整
歷史新增辯論 confidence 假說。下一步只等待既有不可回填前向資料。

## 開獎前信心定義

每期 feature builder 只接收已封存 `decision`，不能取得 `reveal`：

`confidence = (z(top10 support margin) - z(mean candidate disagreement)) / sqrt(2)`

z-score 與第 25／75 百分位只用 development 擬合，holdout 完全沿用。
Proposal HHI 與評論 confidence 只作資料品質描述，不依 outcome 調權。

每期皆驗證 15 個唯一 proposal、15 個一對一 candidate score、60 筆唯一
cross-agent critique、90 次合法主號出現及完整 38／49 號排名。

## 資料品質與漂移

| 遊戲 | Development | Holdout | Holdout high | Holdout low | 信心均值漂移 |
|---|---:|---:|---:|---:|---:|
| 威力彩 | 1,308 | 561 | 120（21.39%） | 151（26.92%） | -0.0825 |
| 大樂透 | 1,465 | 628 | 173（27.55%） | 146（23.25%） | +0.0441 |

兩款遊戲 high／low 都超過預註冊 15% 下限，holdout 平均漂移也在
`±0.5` 內，前後半均有兩群樣本。資料來源沒有重複日期／期別，合法性、
時間順序與 ledger hash 全部通過。因此結果不能歸因於閾值造成的空群或
明顯分布崩壞。

## Holdout 結果

單期零模型為 `Hypergeometric(pool, cutoff, 6)`。High-vs-null 使用跨期
完整 convolution；high-minus-low 以兩組完整離散分布枚舉不等樣本數的
平均差。由於群組序列會隨過去歷史自適應，這組 p 在開封後 QA 中降為
fixed-realized-group sensitivity；主要升級證據另使用下節的序列安全
e-value。四個 game／cutoff 各兩項、共八個單尾 p 使用同一 Holm family。

| 遊戲 | 指標 | High−null | High−low | 原始 p（null／low） | Holm p |
|---|---|---:|---:|---:|---:|
| 威力彩 | top-10 | -0.0539 | -0.1108 | 0.7362／0.8170 | 1.0000／1.0000 |
| 威力彩 | top-30 | -0.0618 | -0.0336 | 0.7827／0.6178 | 1.0000／1.0000 |
| 大樂透 | top-10 | +0.0645 | +0.0972 | 0.1924／0.1776 | 1.0000／1.0000 |
| 大樂透 | top-30 | +0.0375 | +0.0261 | 0.3440／0.4190 | 1.0000／1.0000 |

13 期 circular moving-block bootstrap：

| 遊戲 | 指標 | High−null 95% CI | High−low 95% CI |
|---|---|---:|---:|
| 威力彩 | top-10 | [-0.2187, +0.1192] | [-0.3102, +0.0792] |
| 威力彩 | top-30 | [-0.2405, +0.0952] | [-0.2842, +0.1795] |
| 大樂透 | top-10 | [-0.0549, +0.1844] | [-0.0754, +0.2752] |
| 大樂透 | top-30 | [-0.1150, +0.1854] | [-0.2261, +0.2679] |

大樂透 top-10 的 holdout 前後半皆為正，但 development 的
high-vs-null／high-minus-low 為 `-0.0038／-0.0136`，所以不是時間穩定
訊號。大樂透 top-30 development 雖略正，holdout 前半為
`-0.0011／-0.0625`。所有區間皆跨 0。

## 開封後序列安全 QA

High／low 是每期開獎前決定，但 decision 讀取過去歷史，所以完整群組
序列是 predictable adaptive assignment。正式驗收前新增固定 lambda
grid 的 mixture betting martingale；這項修正只增加門檻，沒有改 feature、
outcome、方向或既有失敗條件。

| 遊戲 | 指標 | High−null e-value | High−low e-value | 兩個 anytime／Holm p |
|---|---|---:|---:|---:|
| 威力彩 | top-10 | 0.1548 | 0.0654 | 1.0000／1.0000 |
| 威力彩 | top-30 | 0.1538 | 0.1448 | 1.0000／1.0000 |
| 大樂透 | top-10 | 0.5463 | 0.4797 | 1.0000／1.0000 |
| 大樂透 | top-30 | 0.2894 | 0.1629 | 1.0000／1.0000 |

所有 e-value 都小於 1，代表這份資料甚至沒有累積正向 betting evidence；
八個 anytime-valid p 與其 Holm p 全為 `1.0`。單元測試另完整枚舉一個
群組由前一期結果決定的自適應兩期例子，確認混合 e-value 在公平零模型下
期望仍為 1。

## 決策

預註冊要求 development 正向、兩個 holdout Holm p `<0.05`、兩個區間
下界大於 0、前後半同向及分布門檻全通過；QA 修正後另要求兩個
sequential-safe Holm p `<0.05`。四個候選皆失敗，正式狀態為：

`stop_new_historical_confidence_hypotheses`

這不表示 AI 辯論「應該反著用」；威力彩負值同樣沒有通過負向確認門檻。
它表示在公平模型與目前資料下，沒有可靠依據用辯論自信調整號碼。

## 重跑

```powershell
python -X utf8 debate_confidence.py
python -X utf8 debate_confidence_verify.py --tests-only
```

正式輸出：

- `research/results/debate_confidence.json`
- 預註冊：`DEBATE_CONFIDENCE_PROTOCOL.md`

本研究為純模擬，不構成購買或下注建議。
