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

## Agent 數量消融

`agent-count-ablation-v1` 專門回答「Agent 越多是否越準」。它重用逐期帳本中
開獎前已封存的 15 組提案與 60 次交叉評論，窮舉 2、3、4、5 人共 26 個
子議會；每個子議會維持自己的歷史評等，每期固定只選五注。

```powershell
python -X utf8 agent_ablation_verify.py
```

正式設定會先暖機 60 期，再依時間切成前 70% development 與最近 30%
holdout。每期另跑 200 組固定種子的均勻隨機五注，主要指標是「五注中最佳
一注的主號命中數」，區間採 13 期區塊 bootstrap 2,000 次。驗收入口會依序
跑核心測試、報告契約、完整回歸、正式研究、完整後測與 `git diff --check`。

研究輸出：

- `agent_ablation.json`：方法、資料品質、全部人數與子議會結果。
- `agent_ablation_summary.csv`：2 至 5 人的 development/holdout 摘要。
- `agent_ablation_subsets.csv`：26 個子議會的分段結果。
- `agent_ablation_artifact.json`：已驗證的 Data Analytics 報告資料。

## Agent 品質與替換影子研究

`council-quality-shadow-v1` 不是再增加 Agent 數量，而是在相同 15 組提案、
60 次評論與五注預算下，逐席比較移除與「覆蓋稽核員」替換；同時量測評論
校準、評論者重複度與五種裁判旋鈕敏感度。

```powershell
python -X utf8 council_quality_verify.py
```

development 只用來選被替換席位，最近 30% holdout 只開封一次。兩款遊戲都
通過配對區塊 bootstrap 閘門前，候選只留在 shadow，不能修改正式下一期
號碼。完整方法與目前結論見 `SHADOW_RESEARCH.md`。
