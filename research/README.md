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

## 五注精確機率覆蓋研究

`portfolio-coverage-shadow-v1` 不再調熱號、冷號或 Agent 數量，而是把每期
已封存的 15 組提案窮舉成 3,003 種五注組合。selector 最大化「至少一注
落入任一現行獎級」的二階 Bonferroni 機率下界，再用精確組合計數確認
完整任一獎級與三主號護欄都不低於原規則裁判；任一精確機率下降就自動
退回原選擇。

```powershell
python -X utf8 portfolio_coverage.py
python -X utf8 portfolio_coverage_verify.py --tests-only
```

研究同時列出五注均勻隨機的精確機率基準、逐期結構機率、回顧性命中差與
13 期區塊 bootstrap。selector 不接收 reveal，只能建立新的前向 shadow
arm，不能改寫已凍結號碼，也不代表單注或頭獎機率被改變。
完整數學定義、正式結果與下一個前向 shadow 升級規則見
`PORTFOLIO_COVERAGE.md`。

## Agent 共識完全分散五注研究

`max-coverage-consensus-shadow-v1` 接續上面的 15 選 5 研究。它仍只讀取
開獎前的 15 組提案與 60 筆評論，但不受限於提案原本的五注組合：先彙總
每個號碼的辯論支持，選出 30 個不同主號，再平均分成五注；威力彩另選五個
不同第二區。Agent 共識決定號碼標籤，完全分散結構決定可精算的五注聯集
覆蓋率。

```powershell
python -X utf8 max_coverage.py
python -X utf8 max_coverage_verify.py --tests-only
```

精確組合計數得到威力彩五注完整任一獎級機率 `54.2963%`、大樂透
`15.2966%`；對應三主號護欄為 `19.2041%`、`9.2902%`。兩款遊戲在
development 與 holdout 每一期都不低於 proposal coverage，正式 4,082 期
回跑也不改動 `records/`。這些數值是五注聯集事件，不表示單注、頭獎或
特定號碼的開出機率提高。

後續有限結構證明另外列出三注六號集合的全部 256 個 Venn membership
向量；排除 19 個重複票結構後，237 個逐一整數精算，兩款遊戲的完整任一
獎級與三主號 charge inequality 違規數都是 0。因此完全分散不再只是參考，
而是固定五注的全域最大結構：

```powershell
python -X utf8 structural_optimum.py
python -X utf8 structural_optimum_verify.py --tests-only
```

完整方法、結果與限制見 `MAX_COVERAGE.md` 與 `STRUCTURAL_OPTIMUM.md`。

## 高獎級 Pareto 全域最優補充證書

`five-ticket-high-tier-pareto-proof-v1` 不使用歷史資料，直接以 union
bound、完整獎級整數 DP 與 12 號小池窮舉，驗證完全分散五注沒有用高獎
機率交換低獎覆蓋率。它同時最大化至少 4／5／6 主號，以及威力彩頭獎至
柒獎、大樂透頭獎至陸獎的每個累積聯集門檻。

```powershell
python -X utf8 high_tier_optimum.py
python -X utf8 high_tier_optimum_verify.py --tests-only
```

這是獨立補充證書，刻意保留既有前向登記引用的 v1 結構 proof hash。
完整結果見 `HIGH_TIER_OPTIMUM.md`。

## 五注獎級與逐注邊際機率

`five-ticket-prize-tier-profile-v1` 保留每注 0 至 6 個主號的完整命中向量，
再精確枚舉威力彩第二區，或計算大樂透剩餘特別號的 membership 歸屬。它把
五注聯集事件拆成最高獎級、所有獲獎票券、同時中獎注數，以及第 1 至第 5 注
的邊際聯集機率。

```powershell
python -X utf8 prize_tier_profile.py
python -X utf8 prize_tier_profile_verify.py --tests-only
```

威力彩五注頭獎率為 `0.000022639%`、大樂透為 `0.000035756%`；任一獎
的 `54.2963%`／`15.2966%` 主要由低獎級構成。測試另以 12 號小池逐開獎
窮舉，和動態規劃的每個獎級與多注同中分布逐項比對。完整結果與限制見
`PRIZE_TIER_PROFILE.md`。

## 30 號標籤訊號研究

結構機率達到全域上限後，`label-signal-shadow-v1` 只研究哪 30 個號碼
進入互斥五注。15 個預先固定 ranker 包含 Agent 共識、全歷史熱度、間隔、
13／26／52／104 期冷熱度，以及共識與熱度混合。所有 ranker 只讀目標期
以前的資料；development 只能選一個候選，holdout 不得反過來改選。

```powershell
python -X utf8 label_signal.py
python -X utf8 label_signal_verify.py --tests-only
```

威力彩 development 選到 `cold_13`，但 holdout 的主號聯集相對共識為
`-0.0178`，13 期區塊 95% 區間 `[-0.1159, +0.0749]`，未通過。大樂透
development 沒有同時提高主指標與三個護欄的候選，因此直接保留共識。
Agent 共識相對精確均勻零模型的 holdout 主號訊號，Holm 校正後 p 值分別
為威力彩 `1.0000`、大樂透 `0.3309`，沒有可宣稱的標籤預測力。正式結論
是 `retain_consensus_label_ranking`，詳見 `LABEL_SIGNAL.md`。

## AI 辯論排名內部校準

`debate-main-rank-calibration-audit-v1` 進一步拆開共識排名內部的
top-10、top-20 與 top-30。排名函式只接收開獎前 decision，逐期必須重建
完整 38／49 號排名；開獎答案由獨立評分函式在排名完成後才接收。

```powershell
python -X utf8 debate_rank_calibration.py
python -X utf8 debate_rank_calibration_verify.py --tests-only
```

六項 holdout 超幾何 convolution 雙尾精確 p 共用 Holm family。威力彩
top-10 每期差為 `-0.0264`、Holm p=`1.0000`；大樂透為 `+0.0542`，
但 development 反向、區間跨 0、Holm p=`0.7941`。威力彩
`top10 − 第11～20名` 為 `-0.0374`，95% 區間
`[-0.1854,+0.1034]`，前後半方向相反。因此 guarded／unconstrained
的高 support multiplicity 都沒有校準證據，排名只保留作確定性 tie-break。
完整數字見 `DEBATE_RANK_CALIBRATION.md`。

## AI 辯論逐期信心校準

`debate-confidence-gating-audit-v1` 不再改 cutoff，而是檢查辯論是否知道
自己何時比較可信。唯一預註冊 composite 是 development 標準化後的
top-10 support margin 減 mean candidate disagreement；development
第 25／75 百分位凍結 low／high，holdout 不重分群。

```powershell
python -X utf8 debate_confidence.py
python -X utf8 debate_confidence_verify.py --tests-only
```

兩款遊戲的 holdout high／low 占比、平均漂移與前後半樣本都通過資料品質
門檻。威力彩高信心 top-10 相對公平／低信心為
`-0.0539／-0.1108`；大樂透雖為 `+0.0645／+0.0972`，development
卻為負，兩個區間均跨 0。兩遊戲 top-10／30 的八項單尾精確 p 經 Holm
後全為 `1.0`。開封後方法 QA 另加入 predictable-weight mixture e-value，
八項 anytime-valid Holm p 也全為 `1.0`。因此不建立 gated shadow，正式
停止用相同完整歷史新增 confidence 假說；詳見
`DEBATE_CONFIDENCE.md`。

## 同 30 號五注分組訊號研究

`partition-signal-shadow-v1` 固定使用相同 30 個 Agent 共識主號，只比較
round-robin、順位區塊、蛇形、提案共現／反共現、全歷史與 52 期共現／
反共現，以及固定種子 shuffle。所有候選仍是五注各六號且兩兩互斥，所以
理論結構機率完全相同。

```powershell
python -X utf8 partition_signal.py
python -X utf8 partition_signal_verify.py --tests-only
```

威力彩 development 選到固定種子 shuffle，三主號事件率比 round-robin
高 `+0.0138`，但 holdout 反轉為 `-0.0232`，95% 區間
`[-0.0606, +0.0160]`，最佳命中與任一獎級也同時下降。大樂透 development
沒有通過護欄的替代分組。正式結論為 `retain_round_robin_partition`；
即使別的分組在 holdout 看起來較好，也禁止事後換選。詳見
`PARTITION_SIGNAL.md`。

## 開獎機制訊號稽核

`draw-mechanism-signal-audit-v1` 使用 inner train／inner validation／外層
holdout，檢驗主號標籤、星期、相鄰期重複、威力彩第二區與大樂透特別號。
五個主號候選、前五第二區與共同第二區共用七項 Holm 校正；機制診斷另以八項 Holm
family 校正。

```powershell
python -X utf8 mechanism_signal.py
python -X utf8 mechanism_signal_verify.py --tests-only
```

所有主號候選在外層 holdout 都沒有通過。威力彩 development 前五第二區
`[2,5,3,4,1]` 的外層覆蓋率為 `67.20%`，原始 p=`0.0115`，但 inner
validation 為負、七項 Holm p=`0.0805`，相對共識任一獎的配對 95% 區間
`[-0.0071,+0.0856]` 仍跨 0。因此只建立未來 forward shadow 假說，不替換
現行排序。development top-1 第二區 `2` 相對辯論 baseline 的兩種獲利結構
嚴格獲利差皆為 `+0.00713`，但 inner validation 反向、Holm p=`0.3576`，
兩個區間也跨 0；它同樣只進入不可回填的 v4 forward shadow。完整結果見
`MECHANISM_SIGNAL.md`。

`adaptive-profit-common-special-audit-v1` 再預註冊 expanding、同星期、
rolling 52／104／208 與兩個 EWMA 方法。Inner validation 選出
`rolling_104`，外層 561 期的 guarded／unconstrained 嚴格獲利差為
`+0.01248／+0.01604`，但兩個 95% 區間都跨 0，三項 Holm p 最小
`0.4860`，第二區命中率 `12.2995%` 也低於 `1/8`。所以不建立自適應 v2，
完整 protocol 與結果見 `ADAPTIVE_SPECIAL_PROTOCOL.md`、
`ADAPTIVE_SPECIAL_SIGNAL.md`。

## 前期號碼條件轉移訊號

`lag-transition-signal-audit-v1` 補上既有熱冷、gap、星期與共現研究沒有
涵蓋的 lag-1／lag-2 條件轉移假說。八個候選在結果開封前固定，使用
inner validation 選模、最近 30% holdout 驗證，兩遊戲共 16 個精確零模型
p 值使用 Holm 校正。

```powershell
python -X utf8 transition_signal.py
python -X utf8 transition_signal_verify.py --tests-only
```

正式結果沒有候選同時提高 30 號聯集命中並守住最佳單注、三主號事件與
任一獎護欄，因此不建立重複 forward shadow，也不在新開獎後重開這次
holdout。完整方法與數字見 `TRANSITION_SIGNAL.md`。

## 五注成本後的獲利機率

`five-ticket-profit-pareto-proof-v1` 不再把任一低獎當成五注獲利。威力彩
五注成本 500 元；研究完整枚舉所有 pairwise overlap <= 1 的線性主號
超圖（2,625 個有標籤結構、72 個不等價結構）與 52 個第二區集合分割，
共 3,744 個候選，再以整數 DP 精算八個第二區結果。

```powershell
python -X utf8 profit_probability.py
python -X utf8 profit_probability_verify.py --tests-only
```

每一對票共享一個不同主號且五注第二區相同，會把歷史最低實領壓力口徑的
嚴格獲利率由 `1.382449%` 提到 `5.451218%`，並保留至少四主號的全域
上限；代價是任一獎率降至 `28.415620%`、至少三主號率降至
`18.285343%`。大樂透任一獎已高於五注成本，完全分散仍是獲利率全域
最優。這是獨立 Pareto 候選，不改動既有前向登記。詳見
`PROFIT_PROBABILITY.md`。

從 `profit-portfolio-consensus-forward-v3` 起，這個結構會把同一期
coverage 的 Agent 辯論前 20 名映射成 `guarded_profit` 五注子影子。
它只對新目標期生效，不是正式第五臂，也不改寫 v1／v2 帳本。

## 無 overlap 守門的獲利全域上限

`five-ticket-unconstrained-profit-optimum-proof-v2` 進一步移除至少四
主號護欄。它不逐一硬跑 46,757,209 個有標籤 Venn 解，而以 674 個
multiplicity histogram、158 個三均勻 profile 與六類第二區 macro 放鬆
完整覆蓋全部結構。

```powershell
python -X utf8 unconstrained_profit_optimum.py
python -X utf8 unconstrained_profit_optimum_verify.py --tests-only
```

凍結歷史最低實領壓力口徑的唯一全域最優（忽略票券與號碼重標）是十個
三票子集各配置一個主號、五注第二區相同，嚴格獲利率 `7.462384%`。
任一獎率同時降至 `22.885399%`，所以它是第三個效用端點，不自動替換
coverage 或 guarded profit。完整證明見
`UNCONSTRAINED_PROFIT_OPTIMUM.md`。

v2 同時閉合現行名目獎金的 proper-special 缺口。`3+2` 完整精算
565 個不等價危險結構；`2+2+1` 從 1,721,537 個有標籤 refinement 經
交叉 macro 與 Hunter 上界縮到 10,199 個不等價候選再逐一精算。六類
proper-special 的最緊全域上界為 `1,648,088`，仍嚴格低於共同第二區
候選的 `1,648,101`。

同一個 v3 登記也會把辯論前 10 名映射成 `unconstrained_profit` 子影子。
兩個子影子的建構、結構重算、certificate hash 與 JSON 穩定雜湊由
`research/profit_portfolio_forward.py` 驗證；開獎後使用相同 500 元成本
與凍結至 `2026-07-17` 的歷史最低實領 snapshot 結算。未達固定前向
checkpoint 前只回報累積樣本，不把單期結果解讀為號碼預測力。新 v3 結算
還會把兩個子影子相對 coverage 的嚴格獲利與壓力淨額差，轉成不含原始號碼
或票券的 `profit_portfolio_aggregate`，供下一期 Qwen 作低權重結構護欄；
任何單期結果都不能推翻上述開獎前精確證明。

`profit-common-special-shadow-forward-v4` 會在上述兩個主號結構內另凍結
development top-1 第二區 `2`，與當期辯論 baseline 第二區作未來 paired
比較。候選不通過歷史升級門檻，所以 v4 不改正式四臂或 v3 baseline；
只在新期數累積嚴格獲利事件差，回饋摘要不含候選號、開獎號或票券。

## Proper-score 機率專家堆疊

`online-probability-stacking-shadow-v1` 把五個 Agent、辯論共識與均勻
分布固定成七個專家。每期先用揭曉前提案建立嚴格正值機率，再以主號與
威力彩第二區的 log loss 在揭曉後更新下一期權重。

```powershell
python -X utf8 probability_stacking.py
python -X utf8 probability_stacking_verify.py --tests-only
```

4,082 期描述性 prequential 結果中，三個維度都是均勻專家最佳，最終
均勻權重皆超過 `99.9997%`。因此歷史不支持現有 Agent 偏好能提高號碼
機率；研究先建立 `probability-stacking-shadow-forward-v5`，再由
`probability-score-feedback-forward-v6` 對新目標期封存完整機率質量，
揭曉後計算相對均勻基準的 regret。新開獎只更新更晚一期，並與正式
coverage 做不可回填配對。完整契約與結果
見 `PROBABILITY_STACKING_PROTOCOL.md`、`PROBABILITY_STACKING.md`。

v6 分數另進入 `probability-score-sequential-monitor-v1`；兩款遊戲主號
都須在共同固定 checkpoint 證明資訊增益為正，且威力彩第二區不得退化。
`probability-stacking-promotion-gate-v2` 同時要求票券命中結果與機率
校準通過，舊 v1–v5 不得補成校準樣本。

`probability-label-decision-strength-audit-v1` 再把 top-30 的機率質量提升
換算成模型隱含命中提升，並以公平開獎的精確超幾何變異計算固定 checkpoint
的可偵測尺度。當前威力彩／大樂透效果約需 4.19／18.91 兆個配對才達
單尾 alpha 0.005、power 80% 的近似尺度，因此不新增號碼變體、不修改
既有登記。詳見 `DECISION_STRENGTH.md`。

## 公平零模型安全機率閘門

`null-safe-probability-gate-v1` 把七專家 mixture 轉成合法無序六號子集
likelihood，並用 `6/(pi²s²)` 起始權重的可重啟 e-process 檢查是否真的有
偏離均勻的證據。三個 stream 共用 family alpha `0.05`，每 stream 固定
啟用門檻 `E >= 60`。

```powershell
python -B -X utf8 null_safe_probability.py
python -B -X utf8 null_safe_probability_verify.py --tests-only
```

全歷史最大 e-value 只有大樂透主號的 `2.180271`；威力彩主號／第二區為
`1.000000`／`1.038536`。因此候選目前三個 gate 都關閉，完整機率回退均勻，
並沿用 coverage 票券標籤。以完整無序六號子集／第二區 categorical
proper score 計算，三個 regret 為
`+0.002951／+0.000752／+0.004108`，null-safe 後降為 0。這只證明方法
會消除無證據偏移；未來升級仍須新的不可回填 proper score。舊 stacking
報告的 marginal loss 是不同量尺，不得與完整子集分數混用。

`null-safe-probability-shadow-forward-v7` 已接入同步交易：每個新目標期
封存安全分布、未開牌證據分布與 prior e-process state；完整六號子集分數
只評估安全 forecast，證據 LR 只更新下一期 gate。同步器會把 null-safe
candidate 與同一期 stacking candidate 的 fitted-through、ledger hash 與
模型權重交叉驗證；operational e-process 只消費開獎前已登記的 v7
proper-score 結算，並由凍結基線加上完整 v7 結算帳本決定性重建。既有
v6 登記不回填，也不推進 gate；重跑或晚到 v7 結算不會重複或漏算。

## 時間自適應 stacking 診斷

`temporal-probability-stacking-diagnostic-v1` 以完整歷史做嚴格
prequential 比較：均勻控制、現行累積 marginal 權重法、完整子集累積法，
以及 52／104／208 期 rolling 與 EWMA。主號全部使用合法無序六號子集
log loss；「marginal」只描述權重更新方式，不是評分量尺。

```powershell
python -B -X utf8 temporal_stacking_diagnostic.py
python -B -X utf8 temporal_stacking_diagnostic_verify.py --tests-only
```

`subset_cumulative` 將威力彩主號與大樂透主號相對現行方法的歷史損失
分別縮減 `50.65%`、`93.66%`，但三個 stream 的平均 regret 仍為
`+0.001456／+0.000752／+0.000261`，bootstrap 95% 上界也全部大於 0。
它的改善來自把 uniform 權重推到近乎 100%，不是找到較準號碼。rolling
與 EWMA 因忘記早期負面證據而更差，所以正式決策是維持 null-safe，
不新增時間衰減 Agent，也不接入 watcher。完整規格與結論見
`TEMPORAL_STACKING_PROTOCOL.md`、`TEMPORAL_STACKING_DIAGNOSTIC.md`。

## 抽出順序子集合訊號

`draw-order-subset-signal-audit-v1` 使用官方原始 API 中現行 replay
ledger 未保存的 `drawNumberAppear[:6]`。494 份月檔共 4,082 期通過
100% 覆蓋、零缺值、零重複、零號碼契約錯誤與 raw／ledger 逐期對帳。
銷售額與所有結果後獎金欄位因時間邊界不明或確定在開獎後，全部排除。

```powershell
python -B -X utf8 draw_order_signal.py
python -B -X utf8 draw_order_signal_verify.py --tests-only
```

唯一固定候選是六位置各自使用 Laplace `alpha=1` 的累積 Dirichlet
無放回模型；64-state DP 精確加總目標六號集合的全部 720 個順序。威力彩
與大樂透平均 subset regret 分別為 `+0.024462`、`+0.030719` nats／期，
兩個 bootstrap 95% 區間的下界也都大於 0。條件於每期六號集合的 2,000
次位置排列 p 值為 `0.8411／0.1244`，沒有順序異常。正式決策是不新增
draw-order Agent 或 shadow，維持 null-safe。完整結果與可重跑 notebook
見 `DRAW_ORDER_SIGNAL.md`。

## 持續球號偏差完整子集合機率

`persistent-label-bias-subset-audit-v1` 不再用 top-30 命中作代理，而是把
截至上一期的每號累積次數加固定 Laplace `alpha=1`，以 64-state DP 精確
加總目標完整六號集合的 720 個無放回順序。這是既有歷史頻率排名研究尚未
涵蓋的 proper-score 問題。

```powershell
python -B -X utf8 persistent_bias_signal.py
python -B -X utf8 persistent_bias_signal_verify.py --tests-only
```

威力彩／大樂透平均 regret 為 `+0.039638／+0.049229` nats／期，
13 期 block-bootstrap 95% 區間分別為
`[+0.024001,+0.057069]`、`[+0.031586,+0.070332]`。前後半、最近
52／104／208 期全為正，五項預註冊門檻在兩款遊戲全部失敗。候選對實際
開獎集合的幾何平均機率只有均勻的 `96.11%／95.20%`；歷史次數高低沒有
形成可延續偏差。正式決策是不新增 Agent、future challenger 或 watcher
訊號，維持 null-safe。完整規格與結果見 `PERSISTENT_BIAS_PROTOCOL.md`、
`PERSISTENT_BIAS_SIGNAL.md`。

## 完整六主號機率前緣

`main-subset-probability-frontier-v1` 只納入開獎前預測、對全部合法無序
六主號組合形成正規化分布，且能以相對精確均勻的 log-loss regret 評分的方法。
舊 marginal loss、top-k／票券命中、獎級／獲利事件及第二區／特別號明確排除，
避免把不同量尺混成「號碼機率」。

```powershell
python -B -X utf8 probability_frontier.py
python -B -X utf8 probability_frontier_verify.py --tests-only
```

正式前緣共有 11 個方法。`uniform_null_safe` 的雙遊戲 minimax regret 為 0，
排名第一；10 個非均勻方法在威力彩與大樂透的平均 regret 都大於 0，全部被
均勻模型嚴格支配。最佳非均勻方法 `subset_cumulative` 的 regret 仍為
`+0.001456／+0.000261` nats／期。歷史不支持任何候選提高完整六號開出機率，
所以不新增 Agent 或 watcher 訊號，並停止在同一歷史上繼續搜尋參數。只有
v7 開獎前封存、不可回填的未來完整 subset proper score 能改變決策。完整規格、
排名與驗證證據見 `PROBABILITY_FRONTIER_PROTOCOL.md`、
`PROBABILITY_FRONTIER.md`。

## 相鄰期重複數完整子集合機率

`lag-overlap-subset-probability-audit-v1` 把相鄰期主號交集大小 `K=0,...,6`
建成完整正規化機率模型。候選只維護過去七格計數；Dirichlet prior 精確置中
公平超幾何分布且總強度一，不搜尋窗口、號碼或轉移矩陣。每期先 forecast，
reveal 後才評分與更新。

```powershell
python -B -X utf8 lag_overlap_signal.py
python -B -X utf8 lag_overlap_signal_verify.py --tests-only
```

威力彩／大樂透 raw 平均 regret 為 `+0.009077／+0.007868` nats／期，
13 期 block-bootstrap 95% 區間為
`[+0.002237,+0.016315]／[+0.001492,+0.015857]`。候選幾何平均機率只有
均勻的 `99.10%／99.22%`；歷史最大 e-value `1.0000／7.0883` 均低於固定
門檻 40，gate 啟用 0 次，safe regret 為 0。正式決策是不新增 Agent、
shadow 或 watcher 訊號。完整公式、分布與結果見
`LAG_OVERLAP_PROTOCOL.md`、`LAG_OVERLAP_SIGNAL.md`。

## 完整六主號機率前緣 v2

`main-subset-probability-frontier-v2` 依預註冊無條件加入 lag-overlap raw
模型，原 v1 的 11 列與 artifact 保持 immutable。新候選排名第 10；12 個方法
中 `uniform_null_safe` 仍是 minimax champion，11 個非均勻方法全部被均勻
嚴格支配。

```powershell
python -B -X utf8 probability_frontier_v2.py
python -B -X utf8 probability_frontier_v2_verify.py --tests-only
```

沒有方法通過雙遊戲平均 regret 與 bootstrap 上界都小於 0 的門檻，因此不改
正式機率，停止在同一歷史調 lag 參數，只等待 v7 未來不可回填 proper score。
完整固定來源、排名與證據見 `PROBABILITY_FRONTIER_V2_PROTOCOL.md`、
`PROBABILITY_FRONTIER_V2.md`。

## 開獎星期完整子集合機率

`calendar-weekday-subset-audit-v1` 只檢驗一個預註冊候選：威力彩週一／
週四與大樂透週二／週五各自使用截至上一期的同星期球號計數，加固定
Laplace `alpha=1` 後形成完整六號無放回分布。大樂透 113 期春節加開
保留評分，但固定均勻且不更新正常星期 state。

```powershell
python -B -X utf8 calendar_regime_signal.py
python -B -X utf8 calendar_regime_signal_verify.py --tests-only
```

威力彩／大樂透平均 regret 為 `+0.071037／+0.084567` nats／期，
13 期 block-bootstrap 95% 區間為
`[+0.048799,+0.094467]／[+0.060100,+0.110597]`。前後半及最近
52／104／208 期全為正，候選幾何平均機率只有均勻的
`93.14%／91.89%`。所以星期模型不新增 Agent、challenger 或 watcher；
不再用同一歷史搜尋月份、節日或 prior。完整規格與結果見
`CALENDAR_REGIME_PROTOCOL.md`、`CALENDAR_REGIME_SIGNAL.md`。

## 完整六主號機率前緣 v3

`main-subset-probability-frontier-v3` 無條件把星期候選加入 immutable v2。
正式前緣共 13 個方法；`uniform_null_safe` 仍是 minimax champion，
12 個非均勻方法全部被均勻嚴格支配，星期候選排名第 13。

```powershell
python -B -X utf8 probability_frontier_v3.py
python -B -X utf8 probability_frontier_v3_verify.py --tests-only
```

正式機率、Agent、watcher 與既有前向登記都不改。停止在同一歷史調星期、
月份、節日、窗口或 prior；只接受未來不可回填的完整 subset proper score。
完整固定來源與排名見 `PROBABILITY_FRONTIER_V3_PROTOCOL.md`、
`PROBABILITY_FRONTIER_V3.md`。

## 跨遊戲最近一期 overlap 完整機率

`cross-game-overlap-subset-probability-audit-v1` 對每個目標只取日期嚴格
較早的另一款最新一期；42 個同日來源全部忽略。依來源落在目標球池的標籤數
`m` 分層，以精確公平超幾何 mass 為總強度 1 的 Dirichlet prior，再把
overlap predictive mass 均分給格內全部合法六號集合。

```powershell
python -B -X utf8 cross_game_overlap_signal.py
python -B -X utf8 cross_game_overlap_signal_verify.py --tests-only
```

威力彩／大樂透平均 regret 為 `+0.023938／+0.008117` nats／期，
bootstrap 95% 區間為
`[+0.011440,+0.038322]／[+0.001408,+0.017176]`。候選幾何平均機率只有
均勻的 `97.63%／99.19%`；不新增 Agent、challenger 或 watcher，也不在
同一歷史搜尋球號轉移、lag 或 prior。詳見
`CROSS_GAME_OVERLAP_PROTOCOL.md`、`CROSS_GAME_OVERLAP_SIGNAL.md`。

## 完整六主號機率前緣 v4

`main-subset-probability-frontier-v4` 無條件把跨遊戲候選加入 immutable v3。
14 個方法中 `uniform_null_safe` 仍是 minimax champion，13 個非均勻方法
全部被均勻嚴格支配；新候選排名第 11。

```powershell
python -B -X utf8 probability_frontier_v4.py
python -B -X utf8 probability_frontier_v4_verify.py --tests-only
```

正式機率、Agent、watcher 與前向登記不改。完整來源與排名見
`PROBABILITY_FRONTIER_V4_PROTOCOL.md`、`PROBABILITY_FRONTIER_V4.md`。

## 實體開獎中介資料可用性

`physical-draw-metadata-availability-audit-v1` 全量遞迴掃描 494 份官方 raw
月檔、4,082 期 row schema，並把開獎機、球組、落球順序與異常欄位的
ticket-time 因果資格分開驗證。官方結果資料的實體欄位覆蓋率為 0%。

固定的 `2026-07-17` 大樂透直播樣本可在 20:32:39 看到主獎號機器標示 `2`，
但投注已於 20:00 截止，且沒有可可靠對應的球組 ID。加碼百組百萬等其他抽獎
grain 固定排除，不能拿來填主號設備欄位。

```powershell
python -B -X utf8 physical_metadata_audit.py
python -B -X utf8 physical_metadata_audit_verify.py --tests-only
```

現階段 0 筆 observation 通過投注截止前資格，因此不建立設備 Agent、不改號碼、
不接入 watcher。未來可以依固定 schema 蒐集影像 metadata，但在兩款遊戲各
至少 104 個 future 期數、machine／ball-set 完整率各 95% 且每期 assignment
都在截止前公開之前，只能做事後機制診斷。完整證據與限制見
`PHYSICAL_METADATA_PROTOCOL.md`、`PHYSICAL_METADATA_AUDIT.md`。
