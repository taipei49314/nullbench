# 抽出順序沒有提高下一期號碼機率

## 結論

官方 `drawNumberAppear` 是完整、乾淨且目前未被 Agent 使用的新欄位，但固定
的抽出位置模型在兩款遊戲都顯著輸給精確均勻機率。

正式決策是 `retain_existing_null_safe_protocol`：

- 不新增 draw-order Agent。
- 不建立 future-only challenger。
- 不接入 watcher。
- 不修改既有 7/20、7/21 或任何前向號碼。

這次得到的價值是排除一個資料品質良好、直覺上可能有機械意義，但實際會
降低完整六號子集合機率品質的方向。

## 資料品質

| 遊戲 | 原始月檔 | 空月檔 | 有效期數 | 日期 | Row schema | 順序覆蓋 | Raw／ledger 不符 |
|---|---:|---:|---:|---|---:|---:|---:|
| 威力彩 | 223 | 0 | 1,929 | 2008-01-24～2026-07-16 | 1 | 100% | 0 |
| 大樂透 | 271 | 36 | 2,153 | 2007-01-02～2026-07-17 | 1 | 100% | 0 |

大樂透 36 個空月檔恰為 `2004-01`～`2006-12`；這是 API 掃描早於現有資料
起點的合法空回應，不是漏抓。494 份 JSON 全部可解析，`totalSize` 與列數
一致，沒有重複期號、重複日期、缺值、非法號碼、前六碼集合不一致或第七碼
不一致。

排序後的 `drawNumberSize` 與兩份正式 replay ledger 共 4,082 期逐筆完全
相同，因此 `drawNumberAppear[:6]` 可以安全用於「更晚一期」研究。

## 欄位時間邊界

| 欄位 | 可得時間 | 本研究用途 |
|---|---|---|
| `period`、`lotteryDate` | 開獎前排程 | 身分與時間順序，不作號碼特徵 |
| 過去期 `drawNumberAppear[:6]` | 該期開獎後 | 唯一新增模型特徵 |
| 當期 `drawNumberAppear` | 當期開獎後 | 只作 reveal，禁止進當期 forecast |
| `drawNumberSize` | 開獎後 | 正式 ledger 對帳與 proper-score target |
| `sellAmount` | 無可靠發布 timestamp | Fail-closed 排除 |
| `totalAmount`、`*Assign`、中獎人數、獎金 | 開獎後 | 排除 |
| `redeemableDate` | 結果發布內容 | 排除 |

銷售額即使在物理上可能於截止售票後確定，只要 API 沒有可驗證的開獎前
timestamp，就不能假設模型當時拿得到。

## 固定模型

模型在看結果前已凍結，沒有參數搜尋：

- 六個抽出位置各自累積每個球號的歷史次數。
- 每格使用固定 Laplace prior `alpha=1`。
- 第 `t` 期 forecast 只使用第 `t-1` 期以前的計數。
- 每個位置在剩餘球中依其位置權重作無放回抽樣。
- 以 64-state dynamic programming 精確加總目標六號集合全部 `6! = 720`
  種抽出順序。
- Proper score 評估完整無序六號集合，不用較容易改善、但與投注無關的
  ordered sequence loss。

零歷史時，兩款遊戲的 DP 都精確回到 `1/C(N,6)`；小型 8 號球池另以全部
720 條路徑與全部 28 個六號集合窮舉，逐項驗證機率與總和。

## Proper-score 結果

Regret 定義為模型 loss 減精確均勻 loss；負值才是機率改善。

| 指標 | 威力彩 | 大樂透 |
|---|---:|---:|
| 平均 regret（nats／期） | +0.024461981 | +0.030719204 |
| 13 期 block bootstrap 95% | `[+0.013443800,+0.035400518]` | `[+0.020186718,+0.041729655]` |
| 前半平均 regret | +0.034995217 | +0.042905177 |
| 後半平均 regret | +0.013939661 | +0.018544546 |
| 最近 52 期 regret | +0.001091257 | +0.042535772 |
| 最近 104 期 regret | +0.019444770 | +0.032259853 |
| 最近 208 期 regret | +0.015531172 | +0.022120323 |
| 單期優於均勻比例 | 46.9673% | 45.0070% |
| 最終 e-value | `3.21e-21` | `1.89e-29` |
| 歷史最大 e-value | 2.3598 | 35.8657 |
| Future challenger | 不合格 | 不合格 |

兩款遊戲的 bootstrap 下界都大於 0，表示這不是區間跨 0 的不確定結果；
固定位置模型在完整歷史的 loss 明確較高。前後半與所有最近視窗也沒有形成
可重複的負 regret。

## 抽出順序本身的條件檢定

另固定每一期實際六號集合，只隨機重排六個位置 2,000 次。這可隔離
「哪些號碼被抽中」與「它們被排在哪個位置」：

| 遊戲 | Position-number statistic | 條件排列 p |
|---|---:|---:|
| 威力彩 | 171.524804 | 0.841079 |
| 大樂透 | 270.828222 | 0.124438 |

兩款遊戲都沒有異常位置關聯。即使這個 p 值很小，也只能說明抽出順序可能
不均勻；真正的升級仍必須在無序六號 subset proper score 上勝過均勻。

## 為什麼會變差

每個位置都要估計 38 或 49 個球號權重，但每期每個位置只有一個觀察。把
原本可交換的六個位置拆開後，參數變多、樣本變稀，估計雜訊超過任何可重現
的機械位置差異。模型因此對隨機波動給出過度不均勻的機率，造成正 regret。

這也再次說明：更多欄位、更多 Agent 或更複雜模型不會自動提高號碼機率；
必須由完整 proper score 證明資訊增益。

## 可稽核產物

- 預註冊：`DRAW_ORDER_SIGNAL_PROTOCOL.md`
- 正式程式：`research/draw_order_signal.py`
- CLI：`draw_order_signal.py`
- 驗證器：`draw_order_signal_verify.py`
- 正式結果：`research/results/draw_order_signal.json`
- 可重跑 notebook：
  `output/jupyter-notebook/draw-order-signal-audit.ipynb`
- Audit hash：
  `b357171c4d830bb66f52ae5531d47941241c15ee5cfe744ddd26edf56001b61a`

notebook 已在 Python 3.12 由上到下執行，並與 Python 3.11 正式產物得到相同
audit hash。16 個專項測試與 live-source formal verifier 均通過。

本研究為純模擬。公平開獎下所有合法號碼組合理論等機率，不構成購買或
下注建議。
