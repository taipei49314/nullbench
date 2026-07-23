# AI 辯論主號排名校準

實驗版本：`debate-main-rank-calibration-audit-v1`

## 結論

15 組 Agent 提案形成的主號支持排名，在完整歷史的最近 30% holdout
沒有通過正向或負向校準。現行 `guarded_profit` 與
`unconstrained_profit` 可以繼續用這個排名作確定性 tie-break，但不得宣稱
前 10 名比其他合法號碼更可能開出，也沒有資料理由增加其 multiplicity。

不修改正式號碼、不建立反向映射 shadow。

## 時間邊界與資料品質

排名函式只接收當期開獎前的 `decision`，不能接收 `reveal`。每一期都硬性
要求 15 個唯一提案、15 個一對一辯論分數、90 次主號出現，以及涵蓋完整
38／49 號碼池的唯一排名。排名封存後，另一個函式才接收實際六主號評分。

| 遊戲 | 全資料 | 暖機後 | Development | Holdout | 資料品質 |
|---|---:|---:|---:|---:|---|
| 威力彩 | 1,929 | 1,869 | 1,308 | 561 | 通過 |
| 大樂透 | 2,153 | 2,093 | 1,465 | 628 | 通過 |

`records/` 在分析前後的 SHA-256 都是
`d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

## Holdout 結果

每個 cutoff 的公平零模型是單期
`Hypergeometric(pool, cutoff, 6)`，跨期以完整 convolution 計算雙尾精確
p 值。兩款遊戲的 top-10／20／30 共六項使用同一個 Holm family；區間為
13 期 moving-block bootstrap。

| 遊戲 | 指標 | 每期命中差 | 95% 區間 | 原始 p | Holm p |
|---|---|---:|---:|---:|---:|
| 威力彩 | top-10 | -0.0264 | [-0.0994, +0.0574] | 0.5486 | 1.0000 |
| 威力彩 | top-20 | -0.0153 | [-0.1258, +0.0881] | 0.7641 | 1.0000 |
| 威力彩 | top-30 | -0.0096 | [-0.0791, +0.0582] | 0.8225 | 1.0000 |
| 大樂透 | top-10 | +0.0542 | [-0.0127, +0.1242] | 0.1532 | 0.7941 |
| 大樂透 | top-20 | +0.0510 | [-0.0254, +0.1275] | 0.2694 | 1.0000 |
| 大樂透 | top-30 | +0.0686 | [-0.0158, +0.1546] | 0.1324 | 0.7941 |

大樂透 holdout 的差雖為正，development 的 top-10、top-20 與 top-30
分別為 `-0.0204`、`-0.0394`、`-0.0018`，方向沒有時間重現，所有區間也
跨 0。威力彩 top-10 的 development 與 holdout 都略為負，但 holdout
前後半分別為 `-0.1218` 與 `+0.0687`，不符合負向校準。

## Multiplicity 檢查

`guarded_profit` 給排名前 10 名較高 multiplicity，因此另用每期
`top10 命中 − 第11～20名命中` 作 paired block-bootstrap：

| 遊戲 | Development | Holdout | 95% 區間 | Holdout 前半／後半 |
|---|---:|---:|---:|---:|
| 威力彩 | -0.0336 | -0.0374 | [-0.1854, +0.1034] | -0.2250／+0.1495 |
| 大樂透 | -0.0014 | +0.0573 | [-0.0589, +0.1704] | +0.0732／+0.0414 |

威力彩是實際映射決策的對象；其方向不穩定且區間跨 0，所以 guarded 與
unconstrained 的高支持映射都沒有校準證據。這不會改變已證明的五注結構
機率，只把「高 support 較可能開出」從可宣稱內容中移除。

## 重跑

```powershell
python -X utf8 debate_rank_calibration.py
python -X utf8 debate_rank_calibration_verify.py --tests-only
```

正式資料：

- `research/results/debate_rank_calibration.json`
- 預註冊：`DEBATE_RANK_CALIBRATION_PROTOCOL.md`

完整歷史已被多項研究使用，因此即使日後提出新方向，也只能先進入不可
回填的未來 shadow。本研究為純模擬，不構成購買或下注建議。
