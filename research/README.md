# 歷史策略研究層

本目錄是正式 v1 以外的唯讀歷史研究區。它只讀 `data/raw/`，結果只寫
`research/results/`；`records/`、W30 凍結票與 PREREG v1 都不在寫入範圍。

## 決策問題

1. 經濟上應不應參與？
2. 如果固定做五注純模擬，哪個政策在未見資料相對純隨機最穩健？

第一題的基準是 `no_play`。第二題才比較熱號、冷號、外觀均衡、反熱門與
現行五人格組合；不得用第二題的歷史第一名推翻第一題。

## 防止過度擬合

- 每週特徵只讀該週以前的開獎。
- 前 50% 週：粗參數搜尋與冠軍附近細調。
- 中間 25% 週：從五種最終投資組合選一次。
- 最後 25% 週：封存測試，只開封一次，不回頭調參。
- 不同策略共享底層均勻亂數，做同週、同 replica 配對比較。
- 主要指標排除頭獎與貳獎；固定獎級差異另作敏感度護欄。
- 外驗必須同時通過 95% 區間、replica 一致性與有差異週勝率。

## 執行

```powershell
python -X utf8 research_verify.py
```

這個單一入口依序執行資料品質、策略搜尋、validation/holdout、決策報告
四組完整測試，再跑全套測試、8 個 replica 與 1,000 次 13 週區塊
bootstrap 的正式研究，最後重跑全套測試與 `git diff --check`。任何階段失敗
都不會繼續。若只要開發期快速驗證，可用 `python research_verify.py
--tests-only`。

可重現分析筆記本：

`output/jupyter-notebook/strategy-walkforward-research.ipynb`

研究輸出：

- `strategy_research.json`：方法、候選、選擇與最終決策。
- `strategy_summary.csv`：粗搜、細調與最終政策的分段指標。
- `policy_weekly.csv`：最終政策逐週平均結果。
- `DECISION.md`：簡潔決策稿。
