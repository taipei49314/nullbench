# 已結算錯誤回饋契約

`settled-forward-feedback-v1` 補上自動模擬 loop 中「開獎後先檢討，再決定下一期」的資料流。它不把單期開獎解釋成可預測規律，也不把上一期漏掉的號碼交給模型追逐。

## 固定交易順序

每次偵測到新開獎時，必須依序完成：

1. 抓取並驗證官方資料。
2. 只結算開獎前已存在的 `final-judge-forward-v1` 登記。
3. 為每筆新結算建立固定格式 postmortem，寫入同一條 append-only 雜湊鏈。
4. 建立嚴格早於下一目標期、最多 13 期的回饋記憶。
5. 驗證回饋 schema、來源雜湊、時間界線與彙總值。
6. 將已驗證回饋連同 15 組既有候選交給 `qwen3:8b`。
7. Qwen 仍只能選 5 個既有 proposal ID；完成後才凍結下一期控制臂與
   coverage shadow。

若結算、帳本或完整回放交易失敗，不得建立新的前向登記；既有結算可保留，下一輪會冪等重試。
若回饋驗證或 Qwen 生成失敗，則明確降級為可重現規則裁決：仍可凍結規則與隨機控制臂，
但 Qwen 臂永久標為不合格，不得冒充已使用回饋的模型結果。

## Postmortem 只允許的資訊

固定診斷只保留：

- Qwen、規則及均勻隨機五注的最佳主號命中數。
- Qwen 相對規則與隨機基準的差值。
- 五注主號聯集大小與聯集命中數。
- 漏號數量，不含漏掉的是哪些號碼。
- 重複選中但未命中的號碼數量與總占位數，不含號碼本身。
- 由上述欄位決定的固定診斷旗標。
- 若該期在開獎前已凍結 coverage v3 獲利子影子，另保留相同 500 元成本下
  coverage、`guarded_profit`、`unconstrained_profit` 的
  `empirical_floor_stress_strict_profit`、壓力測試淨額，以及兩個子影子
  相對 coverage 的差值。這個可選欄位不含票券、號碼或獎級明細。
- 若該期另有 v4 共同第二區 shadow，逐結構再保留相對同主號 baseline 的
  嚴格獲利差與壓力淨額差。回饋刻意不含候選第二區、實際開獎號或票券。
- 若該期有 v6 開獎前機率評分膠囊，另保留主號與適用時第二區的 log loss、
  均勻基準 loss、regret、verdict、candidate／protocol／capsule hash 與
  eligible 狀態。完整機率陣列及號碼標籤不進入 postmortem。

原始開獎號碼、上一期漏號、熱號、冷號與任何可用來追號的清單都不得進入下一輪回饋。
歷史 v1／v2 或沒有獲利子影子的結算維持原 schema 與 hash，不事後補欄位。

## 回饋記憶

- 每款遊戲分開建立。
- 只讀取目標期之前已結算且 postmortem 雜湊有效的資料。
- 視窗上限固定為最近 13 期。
- 每個 row 保留來源 `postmortem_hash`；整體另有 `feedback_hash`。
- 彙總值會在讀取時重新計算，不能只靠重新寫入 hash 掩飾竄改。
- 空記憶也是合法且有 hash 的明確狀態 `verified_empty`。
- 視窗內若有 v3 獲利回顧，另產生 `profit_portfolio_aggregate`：逐策略保存
  登記結算數、合格配對分母、嚴格獲利次數、coverage 對照次數、淨額差平均、
  最近一次結果與 verdict 次數。所有比較只計入 eligible 前向配對。
- 若有 v4 結算，`profit_portfolio_aggregate.common_special_shadow` 只保存
  共同第二區相對 baseline 的 eligible 分母、事件差、淨額差與 verdict 次數；
  Qwen 看不到第二區號碼。
- 若有 v6 結算，`probability_score_aggregate` 只彙總 eligible 配對的平均
  loss、平均均勻 loss、平均 regret、最近 regret 與 verdict 次數。標籤層
  分數與 coverage 結構層結果分開，且 Qwen 看不到實際號碼或機率陣列。

Qwen 回傳的公開裁決資料包含 `feedback_provenance`：狀態、回饋 hash、結算期數、截至目標與來源 postmortem hashes。即使模型失敗而降級為規則裁決，這份來源證明仍會保留。
前向登記另外封存完整但不含原始號碼的 `feedback_context`；驗證器會依當時已出現在帳本中的結算事件重建 context，不能用格式正確但來源不存在的 hash 冒充。

## 誠實護欄

- 單期落差不是因果證據。
- 不追逐上一期漏號。
- 不從單期結果提升熱號或冷號權重。
- 只把重複出現的覆蓋、集中或相對表現當作組合結構護欄。
- 獲利彙總只可作低權重結構護欄；Qwen 不得由單期輸贏反推號碼，也不得用
  少量前向結果推翻開獎前完成的精確有限枚舉證明。
- 不因 postmortem 自動改動 Agent 數量、學習率或統計閘門；任何參數實驗必須另開版本並使用 development/holdout。

驗收入口：

```powershell
python forward_verify.py
```

專用測試涵蓋 schema、雜湊、獲利差值與 proper-score 重算、禁止原始號碼、
未來資料拒絕、舊帳本相容、執行順序、模型降級與登記冪等性。

proper-score 回饋與升級判斷分開：Qwen 只取得最近 13 期的無號碼摘要；
`probability-score-sequential-monitor-v1` 則保留全部合格 v6 分數，並只在
固定共同 checkpoint 評估。`probability-stacking-promotion-gate-v2` 要求
命中結果與機率校準兩條證據都通過，單期分數不得直接調整正式策略。
