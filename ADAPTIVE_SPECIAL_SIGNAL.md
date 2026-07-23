# 威力彩共同第二區自適應訊號結果

`adaptive-profit-common-special-audit-v1` 檢驗共同第二區是否應依近期資料或
開獎星期自適應。候選家族、tie-break、時間切分與升級門檻先凍結在
[ADAPTIVE_SPECIAL_PROTOCOL.md](ADAPTIVE_SPECIAL_PROTOCOL.md)，再第一次執行
inner validation 與外層 holdout。

結論：不建立 v2，保留當期辯論 baseline 與既有固定第二區 v1 shadow。

## 資料品質與切分

- 威力彩 1,929 期，`2008-01-24`～`2026-07-16`。
- 日期與期別重複均為 0；非法開獎 0；時間排序與 replay hash chain 通過。
- 暖機 60 期。
- Inner train 915 期、inner validation 393 期、外層 holdout 561 期。
- 每期方法只讀取嚴格更早的第二區，rolling／EWMA 可依固定規則使用先前
  已揭曉期數更新狀態。
- 正式 `records/` tree hash 前後同為
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

## Inner validation

七個預註冊方法中，四個同時高於公平第二區基準，且在 guarded 與
unconstrained 兩種結構的嚴格獲利差都為正：

- `rolling_104`
- `rolling_208`
- `ewma_half_life_52`
- `ewma_half_life_104`

依凍結的 min-delta 選模規則，唯一入選者是 `rolling_104`：

| 指標 | Inner validation |
|---|---:|
| 第二區命中 | 54／393（13.7405%） |
| 公平基準 | 12.5000% |
| Guarded 嚴格獲利差 | +2.2901 個百分點 |
| Unconstrained 嚴格獲利差 | +1.0178 個百分點 |
| Guarded 平均壓力淨額差 | +NT$14.27／期 |
| Unconstrained 平均壓力淨額差 | +NT$17.14／期 |

這些數值只用於選模，不能當確認性證據。

## 外層 holdout

只有 `rolling_104` 被允許進入 561 期外層 holdout：

| 指標 | Rolling 104 | 辯論 baseline | 差／區間 |
|---|---:|---:|---:|
| 第二區命中 | 69／561（12.2995%） | 63／561（11.2299%） | 相對公平 -0.2005 個百分點 |
| Guarded 嚴格獲利 | 5.8824% | 4.6346% | +1.2478 pp；95% CI `[-0.5348,+3.0348]` pp |
| Unconstrained 嚴格獲利 | 8.5561% | 6.9519% | +1.6043 pp；95% CI `[-1.0695,+4.0998]` pp |
| Guarded 平均壓力淨額差 |  |  | +NT$10.85／期 |
| Unconstrained 平均壓力淨額差 |  |  | +NT$12.35／期 |

三項預註冊 Holm 校正 p：

- Guarded strict-profit：`0.4860`
- Unconstrained strict-profit：`0.4860`
- 第二區命中：`0.5762`

兩種獲利事件差方向仍是正值，但區間都跨 0，第二區命中率也沒有高於公平
基準，三項 Holm p 均遠高於 0.05。這不足以區分真實提升與抽樣波動。

## 決策

- `adaptive-profit-common-special-forward-shadow-v2`：不建立。
- 不改現行 Agent 辯論第二區。
- 不改固定 `profit-common-special-forward-shadow-v1` 候選 `2`。
- 不回填既有前向期數，也不把 rolling 104 的正點估計放進 Qwen 回饋。
- 若未來要重新研究其他窗口或模型，必須另開新 protocol；不能對 v1 結果
  追加候選或事後換門檻。

執行與驗收：

```powershell
python -X utf8 adaptive_special_signal.py
python -X utf8 adaptive_special_signal_verify.py --tests-only
```

正式產物：

- `research/results/adaptive_special_signal.json`

純模擬；所有合法第二區在公平模型下理論機率相同，不構成購買或下注建議。
