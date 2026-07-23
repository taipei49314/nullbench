# 終局裁判前向 A/B 預註冊

實驗版本：`final-judge-forward-v1`

## 問題

在相同 15 組開獎前提案、相同 60 次交叉評論與固定五注預算下，
本機 `qwen3:8b` 終局改選是否比可重現規則裁判穩定提高命中？

## 每期控制臂與 coverage shadow

1. `rule_five`：規則裁判選出的五注。
2. `qwen_five`：qwen3:8b 只能從同一批提案改選的五注。
3. `random_five`：同一期固定種子的均勻隨機五注。
4. `coverage_five`：`profit-portfolio-consensus-forward-v3` 延續 v2，
   彙總同一批 15 組
   提案的辯論分數，選出支持最高的 30 個不同主號並平均分散為五注；威力彩
   另選五個不同第二區。30 個主號互斥使十組票對的完整中獎事件交集各自
   達到全域最小；`five-ticket-structural-optimum-proof-v1` 已進一步證明
   完整任一獎級與三主號聯集機率為全域最大，再逐期確認都不低於規則臂。

新登記的四臂必須在目標開獎日 20:30（Asia/Taipei）前寫入
`simulation/forward/ledger.jsonl`。沒有開獎前登記、晚登、Qwen 降級或
模型來源無法驗證的期數，不得補做為有效 Qwen／規則配對。

威力彩 `2026-07-20` 與大樂透 `2026-07-21` 已凍結的三臂登記保持原樣；
驗證器依登記內的 `coverage_experiment_id` 區分舊三臂、v1 proposal
coverage、v2 共識完全分散與 v3 獲利子影子，絕不回填 coverage 號碼。

威力彩 v2／v3 coverage 另可在同一臂 metadata 內凍結
`special-frequency-forward-shadow-v1` 配對子影子：它複製完全相同的
30 主號、五注分組與全域最優結構，只把第二區替換成研究期前已凍結的五號
候選。它不是第五個臂、不替換 `coverage_five`，也不影響 Qwen／規則比較；
缺少候選證明或 hash 不符時直接省略。

威力彩 v3 在同一份 metadata 內再凍結兩個獲利目標子影子，兩者都只用
同一期 Agent 辯論後、開獎前的主號支持排序，且五注第二區使用辯論支持最高
的 coverage 第二區：

- `guarded_profit`：取前 20 名；十個 ticket pair 各共享一個不同主號，
  每張票另有兩個單獨主號。保留至少四主號的全域最大值，歷史最低實領
  壓力口徑嚴格獲利率為 `5.451218%`。
- `unconstrained_profit`：取前 10 名；十個三票 membership 各配置一個
  主號。凍結壓力口徑嚴格獲利率為 `7.462384%` 的全域最大結構。

它們不是新增正式 arm、不替換 `coverage_five`，也不宣稱前 10／20 名號碼
本身較可能開出；它們只改變五注之間的重疊結構。v1／v2 或已存在的期數
不得事後加入這兩個 shadow。

威力彩 `profit-common-special-shadow-forward-v4` 保留 v3 的兩種主號結構，
另把共同第二區由當期辯論 baseline 改成機制研究在 development 凍結的 `2`。
它只對新目標期生效，候選、兩份結構證明與整個票組都有穩定 hash；任何欄位
被移除或重算外層 hash，語意重建仍會拒絕。v4 不替換 v3 baseline、不新增
正式 arm，也不回填已存在的 7/20、7/21 或任何已揭曉期數。

`probability-stacking-shadow-forward-v5` 對兩款遊戲另凍結 proper-score
七專家混合後的五注。它不替換 `coverage_five`，只比較不同 30 號標籤；
候選的 fitted-through 必須早於目標期，且新揭曉只能更新下一期。完整歷史只
初始化權重，升級只接受新登記的 future-only 配對。既有 7/20、7/21 不加入
此 shadow。

`probability-score-feedback-forward-v6` 再對每個新目標期封存完整主號
機率質量與威力彩第二區機率質量。開獎後以 log loss 對均勻基準計算
regret，號碼標籤分數與 coverage 結構指標分開累積；只把無號碼摘要交給
下一輪回饋，既有 v1–v5 登記不補寫。

`null-safe-probability-shadow-forward-v7` 另封存兩份不同用途的完整分布：
安全分布是該期真正接受評分的 forecast；未開牌 stacking 分布只用來更新
e-process。登記同時封存 prior state 與 gate，主號以完整合法無序六號子集
likelihood 計分。當 prior e-value 未達 `60` 時，安全分布必須精確均勻且
票券沿用 coverage；當期 reveal 只能更新下一期 gate。v6 與更早登記不回填。

## 指標與門檻

- 主要指標：每期五注中最佳一注的主號命中數。
- 次要護欄：每期五注總主號命中差不得為負。
- 區間：13 期循環連續區塊 bootstrap 2,000 次。
- 固定 checkpoint：每款遊戲各在 `52／104／208／416／832` 個合格配對
  才開一次資料；兩個 checkpoint 之間不更新推論區間。
- Qwen alpha spending：每款遊戲五次 look 各使用 lower-tail alpha
  `0.005`，合計不超過 `0.025`；避免每期重看普通 95% 區間造成假陽性膨脹。
- 支持門檻：只開兩款遊戲都完成的共同 checkpoint。兩款遊戲的 Qwen－規則
  主要指標必須在該次相同前綴區間下界皆大於 0，且總主號命中平均差皆不為
  負；不得拼接不同 checkpoint 的個別支持。
- Coverage shadow：每期先驗證完整任一獎級與三主號護欄的精確聯集機率
  都不低於規則臂，且結構證明版本與 certificate hash 必須吻合；兩款遊戲
  在相同固定 checkpoint 檢查 coverage－規則的最佳主號命中差。獨立
  `five-ticket-high-tier-pareto-proof-v1` 補充證明至少 4／5／6 主號與
  高獎級累積門檻也同時達到全域上限，不存在高獎換低獎的隱藏取捨。
- Guarded 獲利子影子：`five-ticket-profit-pareto-proof-v1` 證明威力彩若把
  效用改成五注合計嚴格獲利，pairwise overlap=1 且第二區全同可提高獲利
  事件率，但會降低任一獎與三主號率。v3 只把它登記成未來配對子影子，
  不回填、不替換 coverage，也不改寫既有四臂主要指標。
- 無守門獲利證明：`five-ticket-unconstrained-profit-optimum-proof-v2`
  證明歷史最低實領壓力與現行名目獎金兩種口徑的嚴格獲利全域最大結構
  都是完整三票共享設計，機率 `7.462384%`；它會同時降低任一獎、三主號
  與四主號率。v3 同樣只登記成未來配對子影子，不新增、回填或替換前向臂。
- 獲利子影子前向門檻：每期以凍結的 500 元五注成本，分別記錄實際保守
  反事實獎金與 `2026-07-17` 截止的歷史最低實領壓力獎金；只在
  `52／104／208／416／832` 個共同合格配對 checkpoint 檢查相對 coverage
  的嚴格獲利事件差。Guarded／unconstrained 採任一支持的同一 family，
  所以每個結構每次 look lower-tail alpha 為 `0.0025`，十次可能檢查合計
  不超過 `0.025`。checkpoint 前固定為 `collecting_forward_data`。
- 第二區配對子影子：只適用威力彩；在相同固定 checkpoint 比較
  「歷史第二區－共識第二區」任一獎事件差。區間下界未大於 0 一律
  不支持；歷史探索 p 值不能代替未來樣本。
- 共同第二區獲利子影子：兩個獲利結構分別在固定 checkpoint 比較
  「development top-1 第二區－當期辯論 baseline」的嚴格獲利事件差；
  兩結構另成一個同樣以每 look `0.0025` 控制的 family，同時保存壓力
  淨額差。歷史正差不能取代新 forward 分母，區間下界未大於 0 一律不支持。
- Probability stacking 子影子：主要指標是 stacking－coverage 的 30 號
  聯集主號命中差；最佳單注主號、三中以上與任一獎平均差都是護欄。兩款遊戲
  必須在同一 `52／104／208／416／832` checkpoint 的主要指標區間下界都
  大於 0 且全部護欄非負；每遊戲每次 look lower-tail alpha 為 `0.005`。
- Probability score 校準：只納入 v6 開獎前已封存膠囊的 eligible 分數。
  每期主號資訊增益是均勻基準 loss 減模型 loss；兩款遊戲必須在同一固定
  score checkpoint 的 bootstrap 下界都大於 0，威力彩第二區平均資訊增益
  另須非負。stacking 只有在命中結果與機率校準都 supported 時才可升級。
- Null-safe score：只納入 v7 開獎前已封存膠囊；安全分布用完整合法子集
  log loss 對均勻基準評分，證據分布的 LR 只更新下一期
  `restart-mixture-e-process-v1`。gate 關閉期間的目標期不得使用該期
  reveal 反向啟用非均勻 forecast。

未達最低樣本一律回報 `collecting_forward_data`。樣本足夠但門檻失敗，
回報 `qwen_advantage_not_supported`；不得挑單一遊戲、單一獎級或事後
更換指標翻案。

完整 checkpoint、alpha 與狀態契約見
[SEQUENTIAL_MONITORING.md](SEQUENTIAL_MONITORING.md)；第一筆結算前的
v2 修正與凍結雜湊見
[FORWARD_MONITORING_V2.md](FORWARD_MONITORING_V2.md)。

## 帳本與自動 loop

`python lotto.py sync` 的順序固定為：

1. 抓取官方當月資料。
2. 結算帳本中已登記且現在已有揭曉的目標期。
3. 產生固定 postmortem；若該期有 v3／v4 獲利子影子，同時加入不含票券與號碼的
   coverage／guarded／unconstrained 嚴格獲利及淨額比較，再建立嚴格早於
   下一目標的 13 期回饋。
4. 有新開獎才重建完整逐期 agent loop，並讓 Qwen 讀取已驗證回饋。
5. 先用最新揭曉更新 proper-score stacking artifact，再更新 null-safe
   operational artifact：時間、ledger hash 與模型權重跟隨 stacking，但
   e-process 每次從凍結基線重建，只接受已在開獎前凍結的全部 v7 score；
   v6 空窗不得回補 gate，重跑或晚到 v7 結算不得重複或漏算。
   兩者交叉驗證成功後，從新 manifest 凍結兩款遊戲的下一期
   Qwen／規則／隨機控制與 coverage
   shadow；威力彩同時把 guarded／unconstrained 獲利子影子寫入 metadata，
   若有有效機制研究證書再建立 v4 共同第二區 paired shadow，以及不改主號
   的前五第二區配對子影子；兩款遊戲另加入 v5/v6 stacking 與 v7
   null-safe paired shadow。
6. 重建唯讀摘要 `simulation/forward/status.json`。

下一期回饋只含組合層彙總，不含原始開獎號碼、票券或漏號清單。獲利結果只
計入 eligible 前向配對並作低權重結構護欄，不能用單期輸贏覆寫精確結構證明；
詳細 schema、來源證明與失敗語意見
[FORWARD_FEEDBACK.md](FORWARD_FEEDBACK.md)。

JSONL 是唯一事實源；`status.json` 只是可重建快照。正式 `records/`、
既有歷史回放 JSONL 與過去決策不得因本實驗改寫。

Qwen 的延遲、降級、Token 與五注分散另由
`final-judge-ops-v1` sidecar 觀測；它不改寫本實驗的主要命中指標、最低樣本或
bootstrap 門檻。詳見 [OPS_TELEMETRY.md](OPS_TELEMETRY.md)。

> 本實驗為純模擬。合法組合的理論開出機率相同，不構成購買或下注建議。
