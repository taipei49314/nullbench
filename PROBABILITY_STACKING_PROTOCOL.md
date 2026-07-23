# Prequential 機率專家 Stacking 預註冊

實驗版本：`online-probability-stacking-shadow-v1`

前向版本：`probability-stacking-forward-shadow-v1`

機率評分膠囊：`pre-reveal-probability-score-capsule-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 研究邊界

既有完整歷史已用於 Agent 數量、26 個子議會、席位替換、裁判旋鈕、
號碼標籤、辯論排名、辯論信心、分組、開獎機制與 lag transition 等研究。
因此本實驗禁止再用相同 holdout 宣稱歷史確認，也禁止因描述性歷史結果
修改以下演算法。完整歷史只依真實時間順序初始化線上權重；唯一可支持
策略升級的證據是凍結後、不可回填的未來前向配對。

## 專家與開獎前機率

每款遊戲固定七個專家：

1. 五個既有 Agent，各自只讀當期三組已封存提案。
2. `debate_consensus`，只讀當期 15 組提案的已封存辯論分數。
3. `uniform`，所有主號等權。

每個 Agent 對號碼 `n` 的主號質量為：

`q(a,n) = (該 Agent 三組提案內 n 的出現次數 + 0.5) / (18 + 0.5 × 主號池)`

`debate_consensus` 先對 15 個 `debate_score` 做 temperature=1 的 softmax；
每個提案權重分給該提案六個主號，再加相同的 Jeffreys smoothing `0.5`。
`uniform` 固定為 `1 / 主號池`。所有質量必須嚴格大於零且總和為 1。

威力彩第二區使用相同專家與 smoothing；五個 Agent 的分母改為
`3 + 0.5 × 8`，debate 專家按每個提案的第二區累積 softmax 權重，
uniform 固定為 `1/8`。大樂透不建立可選第二區分布。

## Prequential 權重更新

所有專家初始 `log_weight=0`。第 `t` 期：

1. 先用第 `t` 期開獎前提案與更新前權重建立混合分布與五注。
2. 五注凍結後才讀取當期六個主號；威力彩另讀第二區。
3. 主號 loss 是六個實際主號 `-log(q)` 的平均；第二區 loss 是實際
   第二區的 `-log(q)`。
4. 固定 learning rate `eta_t = 1 / sqrt(t)`。
5. 每個專家更新
   `log_weight -= eta_t × (expert_loss - uniform_loss)`，再整體平移使最大
   log weight 為 0。平移不改混合權重。

當期 reveal 不得影響當期票券，只能影響下一期權重。不得調 smoothing、
temperature、learning-rate schedule、專家集合或 loss。

## 五注映射

- 主號混合分布取前 30 個不同號碼。
- 依機率順位 round-robin 分成五注，每注六號且主號兩兩互斥。
- 威力彩取第二區混合分布前五個不同號碼，依每注主號質量由高到低配對。
- 結構仍須通過 `five-ticket-structural-optimum-proof-v1`，完整任一獎級、
  至少三主號與高獎級全域結構機率不得低於正式 coverage。
- 此 shadow 只改號碼標籤，不新增成本，不替換正式
  `coverage_five`，也不改 guarded／unconstrained 獲利子影子。

## 開獎前機率評分膠囊

從 coverage v6 起，每個新目標期會在 reveal 前另外封存：

- 依號碼自然順序排列的完整 38／49 維主號混合機率質量。
- 威力彩完整 8 維第二區混合機率質量；大樂透固定為不適用。
- 目標期、candidate hash、protocol hash、source decision hash 與
  capsule hash。

揭曉後主號計算六個實際號碼的平均 negative log mass；威力彩第二區
計算實際第二區的 negative log mass。兩者各自減去同定義域均勻分布
的 loss，得到 `regret_vs_uniform`。regret 小於零才代表該期的機率標籤
優於均勻基準。這個分數與五注 coverage 的聯集命中、任一獎及高獎級
結構指標分開保存，避免把固定結構優勢誤認為號碼預測能力。

下一輪回饋只接收 loss、regret、verdict、樣本分母與雜湊，不接收完整
機率陣列、實際號碼或漏號。單期分數只累積，不直接更新策略版本或
promotion 狀態。

## 歷史輸出限制

歷史 prequential 結果只可報告：

- 每款遊戲期數、時間範圍、來源 ledger hash。
- 專家最終混合權重與 log loss。
- stacking 相對正式 consensus coverage 的主號聯集、最佳主號、
  三主號事件與任一獎逐期平均差。
- 前後半方向是否一致，僅作漂移描述。

不得根據上述歷史結果取消或改造 shadow，不計算新的歷史顯著性門檻，
也不得把舊資料的正差寫成「提高下一期機率」。

## 前向主要指標與門檻

- 統計單位：每款遊戲每個開獎前已登記且兩臂皆 eligible 的一期配對。
- 主要指標：stacking 30 號聯集主號命中數減正式 coverage。
- 護欄：最佳單注主號命中差、至少一注三主號事件差、完整任一獎事件差
  的共同 checkpoint 平均都不得小於 0。
- 共同 checkpoint：`52／104／208／416／832`。
- 兩款遊戲必須在同一共同 checkpoint 的主要指標 13 期 circular
  moving-block bootstrap 區間下界都大於 0，且所有護欄通過。
- 每款遊戲五次 look 各用 lower-tail alpha `0.005`；整體是
  intersection-union test，不拼接不同 checkpoint。
- 兩款共同到 832 仍未通過即 `not_supported_final`；要再測必須建立新
  experiment ID。

## Fail-closed

- 15 組提案、60 筆 cross-agent critique、15 個 candidate score、遊戲、
  期別、日期、合法號碼或 ledger hash 任一不符即拒絕。
- 專家欄位缺漏、多餘、非有限值、非正質量、分布不和為 1 即拒絕。
- 模型 artifact 必須保存 fitted-through、參數、log weights、來源 ledger
  hash、protocol hash 與穩定 candidate hash。
- Artifact fitted-through 必須早於目標期；缺少或驗證失敗時省略 shadow，
  不得以正式 coverage 冒充 stacking 成功。
- v6 評分膠囊必須定義域完整、每格有限正值、總和為 1，且來源與內容
  雜湊皆可重算；缺欄、竄改或目標期不符即拒絕整個 stacking shadow。
- 已登記或已揭曉期數不得回填；既有 2026-07-20／2026-07-21 號碼不變。

## v6 校準升級閘門

`probability-score-sequential-monitor-v1` 只接受
`pre-reveal-probability-score-capsule-v1` 在未來開獎後產生的 eligible proper
score。舊 v1–v5 stacking 配對仍保留於命中結果監控，但不得回填為校準樣本。

- 每期主號資訊增益為 `uniform_main_log_loss - main_log_loss`；正值較好。
- 威力彩第二區資訊增益為
  `uniform_special_log_loss - special_log_loss`，只作非負平均護欄。
- 兩款遊戲只在共同 `52／104／208／416／832` 分數 checkpoint 評估。
- 每款遊戲主號使用 13 期 circular moving-block bootstrap；每次 look 的
  lower-tail alpha 固定為 `0.005`，下界都必須大於 0。
- `probability-stacking-promotion-gate-v2` 同時要求命中結果 monitor 與
  probability-score monitor 都為 `supported`。任一者只是收集中、或已
  `not_supported_final`，都不能升級 stacking。

這個閘門刻意把「五注剛好命中」與「完整機率分布真的較準」分開，避免以短期
票券運氣冒充號碼機率改善。

本系統為純模擬。公平開獎下合法號碼標籤理論等機率，不構成購買或下注建議。
