# 累積球號頻率沒有提高下一期完整六號機率

## 結論

`persistent-label-bias-subset-audit-v1` 補上既有研究的機率缺口：不是只問
歷史頻率前 30 名有沒有多命中，而是把所有球號截至上一期的累積頻率轉成
一個合法無放回分布，直接評分下一期完整無序六號集合。

兩款遊戲都明確輸給精確均勻基準。正式決策是
`retain_existing_null_safe_protocol`：

- 不新增持續球號偏差 Agent。
- 不建立 future-only challenger。
- 不接入 watcher。
- 不修改 2026-07-20、2026-07-21 或其他已封存前向號碼。

## 固定模型

結果開封前只封存一個候選 `persistent_dirichlet_1`：

- 每個球號權重為截至上一期的出現次數加固定 Laplace `alpha=1`。
- 六次抽取都在剩餘球號中依相同球號權重做無放回抽樣。
- 以 64-state dynamic programming 精確加總目標六號集合全部
  `6! = 720` 個抽出順序。
- 第 `t` 期先 forecast、後 update；當期號碼只能影響第 `t+1` 期。
- 不搜尋 prior、不挑窗口、不加星期、gap、冷熱號、Agent 分數或特別號。

零歷史時模型精確等於 `1/C(N,6)`。小型 8 號球池另以全部 720 條路徑及
全部 28 個六號子集合窮舉，驗證 DP 與機率總和。

## Proper-score 結果

Regret 是候選完整 subset log loss 減精確均勻基準 loss；負值才代表提高
下一期機率品質。

| 指標 | 威力彩 | 大樂透 |
|---|---:|---:|
| 期數 | 1,929 | 2,153 |
| 平均 regret（nats／期） | +0.039638452 | +0.049228960 |
| 13 期 block-bootstrap 95% | `[+0.024000627,+0.057069435]` | `[+0.031586257,+0.070331732]` |
| 前半平均 regret | +0.064960226 | +0.079334795 |
| 後半平均 regret | +0.014342918 | +0.019151078 |
| 最近 52 期 | +0.001040070 | +0.042423831 |
| 最近 104 期 | +0.019217313 | +0.032838575 |
| 最近 208 期 | +0.015432066 | +0.022699212 |
| 單期優於均勻比例 | 46.7600% | 44.4496% |
| 最終 e-value | `6.20e-34` | `9.31e-47` |
| 歷史最大 e-value | 1.0000 | 33.2414 |

兩個 bootstrap 下界都大於 0，前後半與所有近期視窗也全部是正 regret；
五項凍結門檻在兩款遊戲全數失敗。

從幾何平均機率看，候選對實際開獎集合只給到均勻基準的：

- 威力彩：`exp(-0.039638452) = 96.1137%`
- 大樂透：`exp(-0.049228960) = 95.1963%`

也就是累積頻率造成的機率傾斜，平均把真正開出集合的機率壓低約
`3.89%／4.80%`，不是提高。

## 為什麼頻率高低不能直接當機率

完整歷史的球號次數確實有高低：

- 威力彩每號 `268–341` 次。
- 大樂透每號 `233–292` 次。

但有限樣本中的高低不等於可延續的物理偏差。模型把這些已發生波動當成固定
球號權重，對未來集合給出過度不均勻的機率；下一段資料沒有持續同方向，就
產生正 regret。既有開獎機制稽核也得到 development／holdout 球號殘差相關
接近零或反向，與本次完整 proper score 結果一致。

較強 prior 最多會把候選推回均勻；在沒有新的機械證據前，事後調 prior
只是在同一歷史上搜尋接近 0 的 loss，不能證明負 regret。

## 資料與完整性

- 494 份官方月檔、4,082 期。
- 威力彩 2008-01-24～2026-07-16。
- 大樂透 2007-01-02～2026-07-17。
- 原始資料與正式 replay ledger 逐期零不符。
- `records/` 前後 hash 都是
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。
- Python 3.11 與 3.12 產生完全相同的正式 JSON 與 audit hash。

## 可稽核產物

- 預註冊：`PERSISTENT_BIAS_PROTOCOL.md`
- 正式程式：`research/persistent_bias_signal.py`
- CLI：`persistent_bias_signal.py`
- 驗證器：`persistent_bias_signal_verify.py`
- 正式結果：`research/results/persistent_bias_signal.json`
- Audit hash：
  `201b8494b04165c5246822502845d4c72861d57b3bfee9f4a18e84c4bef140fe`

```powershell
python -B -X utf8 persistent_bias_signal.py
python -B -X utf8 persistent_bias_signal_verify.py --tests-only
```

本研究為純模擬，不構成購買或下注建議。
