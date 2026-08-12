# lotto-lab — 虛擬彩票研究室（純模擬，不下注）

> **日常主力請用 [nullbench](https://pypi.org/project/nullbench/)**（PyPI 可裝、domain 通用、靜態 HTML 報告）。  
> 本 repo 是歷史研究檔案庫（agent loop、訊號協議、結構證明）；新實驗與對外工具走 nullbench。
>
> ```bash
> pip install -U nullbench
> nullbench demo --name try1
> nullbench report --study try1 --open
> nullbench init tw -d taiwan_super --fetch
> ```

> **本系統為負期望值之純模擬實驗，統計上每期獨立。**
> 它不預言號碼；它的正式問題是：「任何選號策略的長期績效，是否顯著異於純隨機？」
> 預期（且樂見）的答案是否——詳見 [PREREG.md](PREREG.md)。

架構承 `ai-company` 紀律：董事會辯論 → 裁決規格 → 測試先行 → 決定性種子 →
append-only 帳本（雜湊鏈）→ null model 併跑 → 繁中報告（結論先行）。
純 Python stdlib，資料來自台彩官方 API（威力彩 2008-01 起、大樂透 2007-01 起全歷史）。

## 桌機戰情室

酷炫前端會直接讀取 `simulation/results/` 的真實逐期辯論、裁決與檢討資料，不使用假資料。
畫面專為 1180px 以上桌機瀏覽器設計：

```powershell
cd frontend
npm install
npm run dev
```

開啟 `http://127.0.0.1:5173/`。前端品質檢查可用：

`npm run dev` 會同時監督桌機背景 watcher；即使關閉瀏覽器分頁，只要桌機伺服器仍在，
它就會每五分鐘重抓台彩官方當月資料。只有偵測到新開獎，才會重新執行揭曉後檢討、
更新 Agent 評分並重建下一期候選。watcher 異常結束會自動重啟，官方 API 失敗則指數
退避重試。手動執行同一流程可使用 `python lotto.py sync`。

```powershell
npm run lint
npm run test
npm run build
```

## CLI 與桌機背景流程（零推播）

```
python lotto.py picks    # 週末/週一開獎前：辯論＋兩遊戲各 5 組＋凍結預註冊
python lotto.py check    # 該週開獎完（建議週六）：抓新開獎→結算→權重更新→產報告
python lotto.py report   # 重新產報告；python lotto.py status 看總覽
python lotto.py ingest   # 手動更新歷史資料（check 會自動做）
python lotto.py loop     # 逐期 agent 辯論閉環：完整歷史回放＋下一期模擬號碼
python lotto.py sync     # 偵測官方新開獎；有新增才重建 agent 閉環
python lotto.py watch    # 無瀏覽器分頁也每 5 分鐘同步；失敗自動重試
python lotto.py forward  # 不抓網路：結算/凍結目前終局裁判前向 A/B
python goal_verify.py --json
                         # 唯讀驗證 7/20、7/21 第一個真實閉環；未完成時 exit 2
python portfolio_coverage.py
                         # 唯讀研究 15 選 5 的完整任一獎級精確機率
python portfolio_coverage_verify.py --tests-only
                         # 機率數學、無前視、完整後端與前端回歸閘門
python exact_selector_audit.py --game super --output research/results/exact_selector_audit_super.json
                         # 精算目前下一期 3,003 種候選組合
python max_coverage.py   # 回跑 Agent 共識＋30 主號完全分散策略
python max_coverage_verify.py --tests-only
                         # 最大覆蓋研究、前向契約與全套回歸閘門
python structural_optimum.py
                         # 256 個 Venn 結構的五注全域最優整數證明
python structural_optimum_verify.py --tests-only
                         # 獨立小池窮舉、證書篡改與全套回歸閘門
python high_tier_optimum.py
                         # 證明高獎級累積門檻與 4／5／6 主號全域最優
python high_tier_optimum_verify.py --tests-only
                         # union bound、小池窮舉與 v1 前向相容驗收
python prize_tier_profile.py
                         # 拆解五注各獎級、多注同中與第 1～5 注邊際機率
python prize_tier_profile_verify.py --tests-only
                         # 精確獎級計數、小池窮舉與全套回歸閘門
python label_signal.py   # 15 種 30 號標籤排序的 walk-forward 封存研究
python label_signal_verify.py --tests-only
                         # 精確零模型、多重比較與全套回歸閘門
python debate_rank_calibration.py
                         # 稽核辯論完整排名的 top-10／20／30 校準
python debate_rank_calibration_verify.py --tests-only
                         # 開獎前邊界、精確 convolution、Holm 與映射驗收
python debate_confidence.py
                         # 稽核高信心期是否真的優於公平零模型與低信心期
python debate_confidence_verify.py --tests-only
                         # 純開獎前特徵、漂移、八項 Holm 與停止規則驗收
python partition_signal.py
                         # 同 30 號的共現／反共現五注分組封存研究
python partition_signal_verify.py --tests-only
                         # 結構不變、無前視與全套回歸閘門
python mechanism_signal.py
python adaptive_special_signal.py
                         # 主號、星期、序列與第二區的巢狀 holdout 稽核
python mechanism_signal_verify.py --tests-only
python adaptive_special_signal_verify.py --tests-only
                         # 資料品質、多重比較、零模型與全套回歸閘門
python transition_signal.py
                         # lag-1／lag-2 條件轉移與 Agent 共識混合稽核
python transition_signal_verify.py --tests-only
                         # 巢狀切分、16 項 Holm 與完整回歸閘門
python probability_stacking.py
                         # 逐期 proper-score 初始化七專家機率權重
python probability_stacking_verify.py --tests-only
                         # 辯論完整性、時間邊界、候選與正式產物驗收
python decision_strength.py
                         # 量化軟機率差被 top-30 放大的程度與可偵測尺度
python decision_strength_verify.py --tests-only
                         # 超幾何精確重算、來源雜湊與唯讀產物驗收
python calendar_regime_signal.py
                         # 同星期累積頻率的完整六號 proper-score 稽核
python calendar_regime_signal_verify.py --tests-only
                         # 星期隔離、加開均勻 fallback 與竄改驗收
python probability_frontier_v3.py
                         # 將星期候選加入 13 方法完整機率前緣
python probability_frontier_v3_verify.py --tests-only
                         # immutable 來源、排名、結論與 live recompute
python cross_game_overlap_signal.py
                         # 嚴格較早另一遊戲最近一期 overlap proper score
python cross_game_overlap_signal_verify.py --tests-only
                         # 同日排除、配對、完整分布與防竄改驗收
python probability_frontier_v4.py
                         # 將跨遊戲候選加入 14 方法完整機率前緣
python probability_frontier_v4_verify.py --tests-only
                         # v3 immutable 映射、排名與 live recompute
```

完全分散策略的精確機率、4,082 期回跑與 v2 前向契約見
[MAX_COVERAGE.md](MAX_COVERAGE.md)。它提高的是固定五注的任一獎級聯集
覆蓋率，不是單注、頭獎或特定號碼的開出機率。全域結構證明見
[STRUCTURAL_OPTIMUM.md](STRUCTURAL_OPTIMUM.md)；54.2963%／15.2966%
分別由哪些獎級組成、真正的五注頭獎率與逐注邊際，見
[PRIZE_TIER_PROFILE.md](PRIZE_TIER_PROFILE.md)。
高獎級沒有被低獎覆蓋率犧牲：頭獎至威力彩柒獎／大樂透陸獎的每個
累積門檻也都達到全域上限，補充證書見
[HIGH_TIER_OPTIMUM.md](HIGH_TIER_OPTIMUM.md)。
號碼標籤的歷史訊號稽核見 [LABEL_SIGNAL.md](LABEL_SIGNAL.md)；目前沒有
通過封存門檻的替代排序，所以不因事後看見 holdout 而換策略。
辯論排名內部的 top-10／20／30 校準另見
[DEBATE_RANK_CALIBRATION.md](DEBATE_RANK_CALIBRATION.md)；六項精確檢定
皆未通過 Holm 與時間穩定門檻，威力彩 top10-vs-next10 區間也跨 0，
所以高 support 只作確定性 tie-break，不宣稱提高開出機率。
逐期辯論是否知道自己何時可信，另見
[DEBATE_CONFIDENCE.md](DEBATE_CONFIDENCE.md)；兩款遊戲的信心分群品質
正常，但四個 top-10／30 候選的區間全跨 0、八項 Holm p 全為 `1.0`，
開封後補強的八項 anytime-valid Holm p 也全為 `1.0`，因此停止再用完整
歷史新增 confidence 假說。
同一批 30 號的五注分組稽核見 [PARTITION_SIGNAL.md](PARTITION_SIGNAL.md)；
目前也沒有通過門檻的共現分組，維持 round-robin。
開獎機制的標籤、星期、序列與第二區稽核見
[MECHANISM_SIGNAL.md](MECHANISM_SIGNAL.md)；威力彩第二區有一個原始訊號，
但未通過巢狀 validation、多重比較及配對區間門檻，所以不改現行號碼；
共同第二區 top-1 也只進入未來 v4 獲利 shadow。
近期／星期自適應共同第二區另見
[ADAPTIVE_SPECIAL_SIGNAL.md](ADAPTIVE_SPECIAL_SIGNAL.md)：`rolling_104`
雖在 inner validation 入選，外層兩種獲利差區間皆跨 0，三項 Holm p
最小為 `0.4860`，因此不建立 v2。
前一期／上兩期的條件轉移假說見
[TRANSITION_SIGNAL.md](TRANSITION_SIGNAL.md)；兩款遊戲的 inner validation
都因中獎護欄下降而保留共識，不建立內容相同的重複 shadow。
前向資料只在固定 checkpoint 開封，避免每期重看造成假陽性；契約見
[SEQUENTIAL_MONITORING.md](SEQUENTIAL_MONITORING.md)。第一筆前向結算前
已再凍結 v2：Qwen 只能在兩款遊戲同一 checkpoint 聯合通過，兩個獲利結構
則共用 Bonferroni family；稽核見
[FORWARD_MONITORING_V2.md](FORWARD_MONITORING_V2.md)。

Goal 稽核在開獎前缺少結算時會標示為等待；目標日台北時間 22:00 後仍沒有官方結果，
會改為阻斷並要求人工檢查，不會無限期把資料缺口當成正常等待。

## 無人值守桌機 Loop

桌機伺服器不再依賴 React 頁面的 timer 才同步。頁面只送出 wake request；常駐
Python watcher 負責真正的下載、揭曉後檢討、Qwen 終局裁決、前向 A/B 結算與
下一期凍結。CLI 與 watcher 共用 OS 單例鎖，不會同時追加同一帳本。

目前 phase、心跳、上次成功、下次檢查與連續失敗會顯示在「驗證」頁。執行歷史
另有 append-only SHA-256 鏈。詳細故障模型見 [AUTOMATION.md](AUTOMATION.md)，
完整驗收使用：

```
python automation_verify.py
```

## 逐期 agent 自動閉環（純模擬）

現行 `agent-loop-v3-unknown-generator` 不先宣告開獎是亂數或有規律。H0
獨立均勻只是一個沒有保留席位的比較基準；H1～H4 分別檢驗時間依賴、
狀態轉換、結構偏差與跨窗反過度擬合。每一期都以完整機率分布的 Brier
proper score 更新後續證據，不能只憑單期命中改權重。

`python lotto.py loop` 會對威力彩與大樂透分別從第一筆歷史資料開始，逐期執行：

1. 嚴格切出目標期以前的歷史，目標期號碼不進入決策。
2. 五個 agent 各提出 3 組候選，共 15 組。
3. 每個 agent 評議其他四位的候選，共 60 筆交叉評議；每筆包含證據分量與信心度。
4. 歷史回放的規則裁判依可信度加權共識、評議分歧、號碼重疊與單一 agent 集中度選出 5 注。
5. 揭曉該期實際結果，量化漏號、重複押錯、未入選提案的事後表現與各 agent 成績。
6. 揭曉後才更新可信度，更新狀態只會影響下一期。
7. 完整回放結束後，僅把「下一期」的 15 組提案與 60 筆評議交給本機 Ollama
   `qwen3:8b` 終局裁決；模型只能選既有 proposal ID，不得自行改號。

逐期決策、辯論、揭曉與檢討會寫入 `simulation/results/<game>.jsonl`。每行含前一行雜湊、
決策雜湊與檢討雜湊，可驗證沒有事後改號；再次執行會從頭決定性重建，不沿用不可稽核的
可變狀態。完整正式驗證使用：

```
python agent_loop_verify.py
```

「最有可能」在此只表示 agent 辯論後的相對排序，不代表合法組合的理論開出機率不同。
`qwen3:8b` 不進入全歷史逐期裁決，以維持位元級重現；它只裁決兩遊戲各一個下一期結果。
模型名稱、五個 proposal ID、合法性、重複組合與理由格式都會再次驗證；失敗時畫面會明確
標示「規則降級」，不會把降級結果冒充為 Qwen。

## 終局裁判前向 A/B

歷史回放不呼叫語言模型，所以歷史帳本不能證明 Qwen 是否比規則裁判好。
`final-judge-forward-v1` 會在每個下一期開獎前，同時凍結：

- 規則裁判五注；
- `qwen3:8b` 從同一批 15 組提案改選的五注；
- 固定種子的均勻隨機五注。
- Agent 辯論支持排序後合成、30 個主號互不重複的 coverage 五注。

`python lotto.py sync` 會先結算已揭曉的舊登記，再凍結新的下一期；沒有開獎前
登記、超過 20:30 才登記或 Qwen 降級的期數永不補做有效配對。前向 JSONL
與摘要位於 `simulation/forward/`，不會修改正式 `records/`。門檻、最低樣本
與禁止事後改指標的規則見 [FORWARD_PREREG.md](FORWARD_PREREG.md)。

新 `profit-portfolio-consensus-forward-v3` 不增加正式 arm，而是在威力彩
coverage metadata 內，用同一份開獎前辯論排序凍結 `guarded_profit` 與
`unconstrained_profit` 兩個五注子影子。前者取前 20 名並保留高獎守門，
後者取前 10 名最大化已證明的歷史最低實領壓力嚴格獲利率；兩者都只在未來
開獎結算，v1／v2 與既有期數永不回填。結算後，同成本的嚴格獲利、壓力淨額
與相對 coverage 差值會以不含票券或號碼的可驗證摘要進入下一期回饋。

`profit-common-special-shadow-forward-v4` 再以相同兩種主號結構，將
development 凍結的共同第二區 `2` 與當期辯論 baseline 作未來配對。歷史
holdout 的嚴格獲利差雖為 `+0.713` 個百分點，但 inner validation 反向且
95% 區間跨 0，因此不升級、不回填，只從下一個新目標期累積前向證據。

`probability-stacking-shadow-forward-v5` 另把五個 Agent、辯論共識與
均勻分布視為七個機率專家，以逐期 log loss 在揭曉後更新權重，再把下一期
機率前 30 名映射為五注完全分散 shadow。完整歷史顯示三個維度都是均勻
專家最佳，所以目前只作 future-only 配對，不宣稱號碼較準。新開獎後會先
更新候選再登記更晚一期，既有 7/20、7/21 不回填。契約與結果見
[PROBABILITY_STACKING_PROTOCOL.md](PROBABILITY_STACKING_PROTOCOL.md) 與
[PROBABILITY_STACKING.md](PROBABILITY_STACKING.md)。

`probability-score-feedback-forward-v6` 再於每個新目標期開獎前封存
完整主號機率質量與威力彩第二區機率質量。開獎後用 log loss 對均勻
基準計算 regret，將「號碼標籤是否較準」與「五注結構是否覆蓋較廣」
分開評分；下一輪只取得無號碼的分數摘要。既有 v1–v5 期數與 hash
維持原樣，不回填 v6 分數。新的升級閘門要求五注命中結果與完整機率
校準都在各自的雙遊戲固定 checkpoint 通過；只靠短期命中不能升級。

`null-safe-probability-gate-v1` 進一步修正現行 stacking 在無訊號時仍留下
極小非均勻質量的問題。它用合法六號子集 likelihood 與可重啟 e-process
作固定證據閘門；三個歷史 stream 的最大 e-value 只有 `2.18`，遠低於
family-wise 門檻 `60`。因此新 future-only 候選在無證據時使用精確均勻
機率，五注標籤仍沿用 coverage；不把同分自然排序、熱冷號或漏號冒充優勢。
契約與結果見 [NULL_SAFE_PROBABILITY_PROTOCOL.md](NULL_SAFE_PROBABILITY_PROTOCOL.md)
與 [NULL_SAFE_PROBABILITY.md](NULL_SAFE_PROBABILITY.md)。

`temporal-probability-stacking-diagnostic-v1` 另外固定比較累積、52／104／208
期 rolling 與對應 EWMA，共九種方法、三個 stream，且每期都先預測再讀取
當期開獎。完整無序六號子集 proper score 顯示，描述性最佳的
`subset_cumulative` 只是更快把主號 uniform 權重推回近乎 100%；三個
平均 regret 仍全部大於 0，bootstrap 上界也跨過 0。時間衰減反而會忘記
早期負面證據並重新追逐雜訊，因此不新增 Agent、不接入 watcher。詳見
[TEMPORAL_STACKING_PROTOCOL.md](TEMPORAL_STACKING_PROTOCOL.md) 與
[TEMPORAL_STACKING_DIAGNOSTIC.md](TEMPORAL_STACKING_DIAGNOSTIC.md)。

`draw-order-subset-signal-audit-v1` 再盤點 494 份官方原始 JSON，找出現行
ledger 未保存的 `drawNumberAppear`。4,082 期抽出順序覆蓋率 100%，與
正式 ledger 零不符；但固定 `alpha=1` 位置模型經 64-state DP 加總全部
720 種順序後，威力彩／大樂透完整六號 subset regret 為
`+0.024462／+0.030719`，bootstrap 區間也全在 0 以上。資料品質很好，
模型卻明確較差，因此不新增 Agent、不建立 shadow。詳見
[DRAW_ORDER_SIGNAL_PROTOCOL.md](DRAW_ORDER_SIGNAL_PROTOCOL.md) 與
[DRAW_ORDER_SIGNAL.md](DRAW_ORDER_SIGNAL.md)。

`persistent-label-bias-subset-audit-v1` 接著補上「歷史球號頻率」的完整
機率量尺。唯一候選只用截至上一期的各號累積次數與固定 Laplace
`alpha=1`，再以精確無放回 DP 評分完整六號集合。威力彩／大樂透平均
regret 為 `+0.039638／+0.049229` nats／期，兩個 bootstrap 95% 區間
連下界都大於 0；前後半與最近 52／104／208 期也全部較差。候選對實際
開獎集合的幾何平均機率只有均勻基準的 `96.11%／95.20%`，因此不新增
Agent 或 shadow，繼續維持 null-safe。詳見
[PERSISTENT_BIAS_PROTOCOL.md](PERSISTENT_BIAS_PROTOCOL.md) 與
[PERSISTENT_BIAS_SIGNAL.md](PERSISTENT_BIAS_SIGNAL.md)。

`main-subset-probability-frontier-v1` 最後把所有能對完整無序六主號分布作
同尺度 proper-score 比較的方法統一排名。11 個方法中，精確均勻
`uniform_null_safe` 的 minimax regret 為 0、排名第一；其餘 10 個非均勻方法
在兩款遊戲的平均 regret 全為正，全部被均勻模型嚴格支配。最接近的
`subset_cumulative` 仍為威力彩 `+0.001456`、大樂透 `+0.000261`
nats／期，不是已發現的號碼訊號。因此停止在同一歷史上繼續調窗口或 prior，
只接受 v7 新期數開獎前封存、不可回填的完整 subset proper score 作翻盤證據。
契約、完整排名與限制見
[PROBABILITY_FRONTIER_PROTOCOL.md](PROBABILITY_FRONTIER_PROTOCOL.md) 與
[PROBABILITY_FRONTIER.md](PROBABILITY_FRONTIER.md)。

`physical-draw-metadata-availability-audit-v1` 再檢查開獎機、球組與落球
順序是否能成為真正的下一期特徵。494 份、4,082 期官方 raw 結果的實體
metadata 覆蓋為 0；固定直播樣本雖可看到大樂透主獎號機器標示 `2`，但公開
時間是 20:32:39，已晚於 20:00 投注截止 32 分 39 秒，且球組 ID 缺失。
因此設備資料目前只能做事後機制診斷，不能改號碼或接入 watcher。詳見
[PHYSICAL_METADATA_PROTOCOL.md](PHYSICAL_METADATA_PROTOCOL.md) 與
[PHYSICAL_METADATA_AUDIT.md](PHYSICAL_METADATA_AUDIT.md)。

`lag-overlap-subset-probability-audit-v1` 再補上既有 transition／機制研究
尚未使用的完整機率量尺：只估計上一期與下一期重複 0～6 個主號的七格分布，
再均分給各格全部合法六號集合。威力彩／大樂透平均 regret 為
`+0.009077／+0.007868`，bootstrap 95% 區間連下界都大於 0；候選對實際
開獎集合的幾何平均機率只有均勻的 `99.10%／99.22%`。`E>=40` gate 歷史啟用
0 次，所以不新增 Agent 或 watcher 訊號。詳見
[LAG_OVERLAP_PROTOCOL.md](LAG_OVERLAP_PROTOCOL.md) 與
[LAG_OVERLAP_SIGNAL.md](LAG_OVERLAP_SIGNAL.md)。

`main-subset-probability-frontier-v2` 無條件加入上述候選、保留 v1 immutable。
12 個方法中均勻 null-safe 仍排名第一，11 個非均勻方法全部被均勻嚴格支配；
lag-overlap 排名第 10。正式機率不改，只等待不可回填的 v7 未來 proper score。
完整排名見
[PROBABILITY_FRONTIER_V2_PROTOCOL.md](PROBABILITY_FRONTIER_V2_PROTOCOL.md) 與
[PROBABILITY_FRONTIER_V2.md](PROBABILITY_FRONTIER_V2.md)。

`calendar-weekday-subset-audit-v1` 只補星期條件的完整機率缺口：正常開獎日
使用截至上一期的同星期累積球號次數與固定 `alpha=1`，正常星期外加開則
精確回到均勻。威力彩／大樂透平均 regret 為
`+0.071037／+0.084567`，bootstrap 區間全在 0 以上；候選對真正開出集合
的幾何平均機率只有均勻的 `93.14%／91.89%`。因此不新增 Agent 或 watcher，
也不再事後搜尋月份、節日或 prior。詳見
[CALENDAR_REGIME_PROTOCOL.md](CALENDAR_REGIME_PROTOCOL.md) 與
[CALENDAR_REGIME_SIGNAL.md](CALENDAR_REGIME_SIGNAL.md)。

`main-subset-probability-frontier-v3` 無條件把星期候選加入 immutable v2。
13 個方法中 `uniform_null_safe` 仍排名第一，12 個非均勻方法全部被均勻
嚴格支配；星期候選排名第 13。正式機率與前向號碼不變。完整排名見
[PROBABILITY_FRONTIER_V3_PROTOCOL.md](PROBABILITY_FRONTIER_V3_PROTOCOL.md)
與 [PROBABILITY_FRONTIER_V3.md](PROBABILITY_FRONTIER_V3.md)。

`cross-game-overlap-subset-probability-audit-v1` 只使用日期嚴格較早的另一款
最新一期，估計共享標籤 overlap 0–6 的完整 subset 分布；42 個同日來源全部
忽略。威力彩／大樂透 regret 為 `+0.023938／+0.008117`，bootstrap 區間
下界都大於 0，候選幾何平均機率只有均勻的 `97.63%／99.19%`。因此不新增
Agent 或 watcher，也不搜尋球號轉移矩陣或 lag 變體。詳見
[CROSS_GAME_OVERLAP_PROTOCOL.md](CROSS_GAME_OVERLAP_PROTOCOL.md) 與
[CROSS_GAME_OVERLAP_SIGNAL.md](CROSS_GAME_OVERLAP_SIGNAL.md)。

`main-subset-probability-frontier-v4` 無條件將它加入 immutable v3。14 個方法
中 `uniform_null_safe` 仍第 1，13 個非均勻方法全部被均勻嚴格支配；跨遊戲
候選排名第 11。完整排名見
[PROBABILITY_FRONTIER_V4_PROTOCOL.md](PROBABILITY_FRONTIER_V4_PROTOCOL.md)
與 [PROBABILITY_FRONTIER_V4.md](PROBABILITY_FRONTIER_V4.md)。

`null-safe-probability-shadow-forward-v7` 已接入背景 loop。它只會出現在
stacking 權重以最新揭曉更新、且 null-safe operational artifact 驗證成功後
建立的全新目標期；每筆登記同時封存
安全分布、未開牌證據分布與 prior e-process state。揭曉後以完整合法六號
子集 log loss 結算安全分布，再以證據分布的 likelihood ratio 更新下一期
gate。只有預註冊 v7 結算可以推進 e-process；既有 7/20、7/21 v6 登記與
hash 維持原樣，不補寫 v7，也不作為 v7 gate 證據。operational state
每次都由凍結基線加上完整 v7 結算帳本決定性重建，避免重跑或晚到結算
造成重複與漏算。

進一步的決策強度稽核顯示，當前模型隱含的每期聯集命中提升只有威力彩
`0.000001550`、大樂透 `0.000000888`，遠低於 832 期設計可辨識的
`0.1100`／`0.1338`。因此 top-30 清單是模擬決策，不是已證實的實質機率
排序；系統不再增加另一套歷史標籤變體。詳見
[DECISION_STRENGTH.md](DECISION_STRENGTH.md)。

同一筆前向登記也會由 `final-judge-ops-v1` 保存 Qwen 延遲、Token、降級原因、
候選分歧與五注覆蓋度；既有缺資料登記不回填。命中證據與運作健康必須同時通過，
才允許進入保留規則控制組的 shadow promotion。規格見
[OPS_TELEMETRY.md](OPS_TELEMETRY.md)。

偵測到新開獎時，系統會先結算舊的前向登記並產生固定、無原始號碼的錯誤診斷，
再把最近最多 13 期的已結算組合層回饋交給下一期 Qwen 裁決。回饋來源 hash、時間界線
與彙總都會重新驗證；若有 v3／v4 獲利結算，Qwen 只會看到 eligible 配對的逐策略
樣本數、嚴格獲利與淨額差彙總，並被限制只能作低權重結構護欄。單期漏號、
熱冷號、票券明細及目標期資料不會進入模型；若有 v6，另只提供 proper-score
的 loss／regret 趨勢，不提供完整機率陣列或號碼。完整契約見
[FORWARD_FEEDBACK.md](FORWARD_FEEDBACK.md)。

完整驗收：

```
python forward_verify.py
```

## 全歷史策略研究（與正式 v1 隔離）

```
python research_verify.py     # 建議：四階段測試 → 正式回測 → 全套驗收
python research_backtest.py   # 只重跑正式研究
```

研究管線會逐週回放全部官方歷史，只允許使用當週以前的資料。前 50% 週用於
粗搜尋與局部細調，接續 25% 用於選擇五注政策，最後 25% 是一次性封存測試集。
結果寫到 `research/results/`，不會讀寫 `records/`，也不會改動已凍結的 v1 票。

「最佳決策」分成兩層：經濟層以不參與為基準；條件式研究層則比較固定模擬
五注時的政策。只有封存測試集相對純隨機的區間、一致性與固定獎級護欄全部
通過，才允許替換條件式 `random_5` 基準。

### Agent 數量消融

```
python agent_ablation_verify.py
```

這個入口會以逐期封存的提案與評論，窮舉 2 至 5 人共 26 個子議會，固定每期
五注，並和每期 200 組均勻隨機五注做配對比較。每個子議會有獨立歷史評等；
60 期暖機後，以前 70% development、最近 30% holdout 檢查「更多 Agent
是否真的提高五注中最佳一注的主號命中」。結果只寫入 `research/results/`，
正式 `records/` 雜湊前後必須一致。

### Agent 品質影子研究

```
python council_quality_verify.py
```

這一層逐席測試移除與「覆蓋稽核員」替換，並量測評論校準、聲音重複及
裁判敏感度。development 選席、holdout 驗證，兩款遊戲未共同通過前只保留
shadow；目前正式五席與 7/20、7/21 已凍結號碼完全不變。桌機前端的
「策略實驗」可點選最近 52 期、Agent 席位、評論模式與裁判旋鈕。

## 五個選號人格（每遊戲每週 5 席）

| 人格 | 席位 | 手法 |
|------|------|------|
| 亂數修士 | 保留第 1 席、權重凍結 | 純均勻隨機——內建活體對照 |
| 熱手獵人 | 權重競爭 | 近 50 期指數衰減頻率加權 |
| 冷灶守望者 | 權重競爭 | 遺漏值加權（賭徒謬誤的忠實代表，收進來就是為了檢驗它） |
| 均衡工程師 | 權重競爭 | 拒絕取樣：和值帶/奇偶/連號/尾數/極差五約束 |
| 反眾道人 | 權重競爭 | 避開生日號碼帶——唯一有理論依據（不改機率、只影響同額分彩） |

每週核對後，各人格的**影子票**成績對 1,000 注 null 票取百分位排名，
乘法權重更新（η=0.10、均勻混合 ε=0.10、clamp [0.05,0.60]、前 8 週 burn-in 凍結）。
權重是**被研究的展品，不是引擎**——理論預期它長期隨機漫步。

## 誠實設計（裁決書 honesty guards）

- **200 組 null 對照**與正式組同種子紀律、同估值、同一條結算程式路徑。
- 出號**凍結預註冊**（content_hash＋code_hash），開獎前落檔，逾時標 LATE 不入正式統計。
- 核對前**種子重放驗證**，號碼不符整週 INVALID。
- 浮動獎金**反事實保守估值**（我們若真中會多一個分獎人），固定/浮動雙帳本永不合併。
- 報告產生器內建**禁用詞 lint**（預測/必中/即將開出/勝率提升/破解 → 拒絕產檔）。
- 正式週期 v1 的本地 Ollama `qwen3:8b` 仍是**評論席**；逐期 agent-loop v3 則讓它在
  15 組合法候選完成 60 次評議後擔任終局裁判，但仍不能自創或修改號碼。

## 五注成本後的獲利機率

`five-ticket-profit-pareto-proof-v1` 把任一獎與五注合計獲利分開。威力彩
完整枚舉 72 個保留至少四主號全域上限的不等價主號結構，以及 52 個第二區
相等模式，共 3,744 個候選。歷史最低實領壓力口徑的嚴格獲利率可由完全
分散的 `1.382449%` 提到 `5.451218%`，但任一獎率會由 `54.296295%`
降至 `28.415620%`。因此它是另一個效用目標，不自動替換已凍結 coverage。
從 coverage v3 起，它會以 `guarded_profit` 子影子對新目標期預先登記，
用未來樣本比較嚴格獲利事件，但仍不替換 coverage 正式臂。

```powershell
python -X utf8 profit_probability.py
python -X utf8 profit_probability_verify.py --tests-only
```

大樂透最低獎仍高於五注成本，任一獎與嚴格獲利事件相同，完全分散結構
繼續是全域最優。完整證明、壓力口徑與限制見 `PROFIT_PROBABILITY.md`。

移除至少四主號守門後，`five-ticket-unconstrained-profit-optimum-proof-v2`
再以 674 個 multiplicity histogram、158 個三均勻 profile 與六類
proper 第二區放鬆上界，證明威力彩歷史最低實領壓力獲利率的全域最大為
`7.462384%`：十個三票共享主號各一次，五注第二區相同。它會把任一獎率
降至 `22.885399%`，因此仍不自動替換 coverage。詳見
`UNCONSTRAINED_PROFIT_OPTIMUM.md`。
v2 另對現行名目獎金的六類 proper-special 完成 single-block 上界、
macro 危險集、degree refinement、Hunter 二階上界與最終整數 DP；最緊
proper-special 全域上界 `1,648,088` 仍低於共同第二區的 `1,648,101`，
因此名目口徑也得到全域最優結論。
coverage v3 也會把它映射到同一期辯論前 10 名，作為
`unconstrained_profit` 未來子影子；帳本保存結構 proof hash、票組 hash、
500 元成本與凍結歷史 floor snapshot。

## 檔案地圖

```
lotto.py              CLI
engine/
  games.py            獎則引擎（獎級判定＋保守估值）
  fetch.py            台彩官方 API 逐月抓取＋不可變快取
  store.py            開獎庫＋ISO 週時間學
  analysts.py         五人格（決定性產號）
  picker.py           席位分配＋出號＋凍結預註冊＋null 票
  settle.py           每週核對（重放驗證→逐期結算→週結→權重）
  strategy.py         權重 replay/更新（無可變狀態檔）
  report.py           繁中週報（結論先行＋lint）
  debate.py           董事會陳述＋AI 評論席
  agent_loop.py       逐期多 Agent 提案、交叉評議、回放與回饋閉環
  qwen_judge.py       qwen3:8b 終局裁判、結構化輸出與嚴格驗證
  decision_observatory.py
                      Qwen 延遲、降級、Token、分散與開獎後品質閘門
  forward_feedback.py
                      已結算錯誤診斷、13 期回饋記憶與防追號驗證
  forward_lab.py      四臂前向帳本、coverage v3 與獲利子影子結算
  automation.py       無分頁背景 watcher、單例鎖、重試與執行歷史
  ledger.py           append-only JSONL（SHA-256 雜湊鏈）
  seeds.py / config.py / stats.py / env.py / ollama_seat.py
data/raw/<game>/      官方 API 原始月回應（估值永遠可離線重放）
records/              picks / settlements / weights / commentary 帳本＋reports/
research/             全歷史走步回測、兩階段搜尋與封存外驗
  profit_portfolio_forward.py
                      辯論排序到 guarded／unconstrained 五注的純函式映射
agent_ablation.py     2 至 5 人共 26 個子議會的正式消融研究
agent_ablation_verify.py
                      分階段測試、正式消融與完整後測入口
council_quality.py    Agent 品質、覆蓋替換、評論校準與裁判敏感度研究
council_quality_verify.py
                      分階段測試、正式影子研究、前端與完整後測入口
forward_verify.py     前向三臂帳本、sync、前端與完整回歸驗收
FORWARD_PREREG.md     Qwen／規則前向比較的凍結門檻
FORWARD_FEEDBACK.md   開獎後先檢討、再裁決下一期的回饋契約
OPS_TELEMETRY.md      Qwen 運作遙測與聯合部署閘門
automation_verify.py  背景 Loop、故障恢復、前端與完整回歸驗收
AUTOMATION.md         桌機 watcher、監督重啟與持久狀態契約
SHADOW_RESEARCH.md    Agent 替換、辯論校準、裁判敏感度與升級閘門
PORTFOLIO_COVERAGE.md 五注任一獎級聯集的精確機率、正式結果與前向閘門
PROFIT_PROBABILITY.md 五注成本後的嚴格獲利率、結構搜尋與 Pareto 取捨
UNCONSTRAINED_PROFIT_OPTIMUM.md
                      威力彩壓力獲利率的無 overlap 守門全域最優證明
output/jupyter-notebook/
                      可重跑的策略研究伴隨筆記本
tests/                研究與正式流程完整測試
```

## 驗證紀律

改任何 engine 邏輯後：`python -X utf8 -m pytest tests -q` 必須全綠。
正式策略研究使用 `python research_verify.py`；資料品質、策略搜尋、
validation/holdout 與決策報告四個階段任一測試或閘門失敗都會立即停止。
改參數＝開新 experiment_id（見 PREREG.md），禁止原地調參沿用舊帳。
