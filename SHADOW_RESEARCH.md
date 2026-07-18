# Agent 品質影子研究

`council-quality-shadow-v1` 不改正式五席、不改下一期號碼，也不寫入
`records/` 或前向 A/B 帳本。它只讀 `simulation/results/*.jsonl` 中每期在
開獎前已封存的 15 組提案、60 次評論與當時評等。

## 研究問題

1. 哪個 Agent 的三組提案提供其他席位沒有的號碼覆蓋？
2. 移除某席位後，固定五注的最佳主號命中與聯集命中如何改變？
3. 用「覆蓋稽核員」替換某席位，是否能在未見 holdout 重複改善？
4. 各評論者的分數與事後主號命中是否有校準關係？
5. 關閉評等、信心度、分歧、五注重疊或同 Agent 集中懲罰時，
   裁決會翻動多少？

## 覆蓋稽核員

覆蓋稽核員每期只讀其他四席已封存的 12 組提案，固定搜尋三組低重疊合法
候選；它不知道當期開獎，也不使用下一期資料。它的評論只量測候選池內的
號碼重複度，因此是分散度角色，不是預測角色。

每個替換實驗都維持 15 組提案、60 次評論及五注預算：

- 被替換 Agent 的三組提案與評論全部移除。
- 其餘四席各評論覆蓋稽核員的三組提案。
- 覆蓋稽核員評論其餘四席的 12 組提案。
- 預設裁判旋鈕與正式規則裁判完全相同。

## 時序與升級閘門

- 每款遊戲先暖機 60 期。
- 暖機後前 70% 是 development，最近 30% 是一次性 holdout。
- 每款遊戲只用 development 選一個「被替換席位」。
- 升級條件是該席位在 holdout 的替換後最佳主號命中差，其 13 期區塊
  bootstrap 95% 區間下界大於 0，且聯集主號命中不下降。
- 威力彩與大樂透必須同時通過；否則候選只留在 shadow。

目前結果：

- 威力彩選中「反眾道人 → 覆蓋稽核員」，holdout 最佳主號命中差
  `+0.0766`，95% 區間 `[+0.0089, +0.1390]`。
- 大樂透選中同一替換，holdout 差 `+0.0382`，95% 區間
  `[-0.0096, +0.0892]`，仍跨過 0。
- 聯合結論為 `retain_current_council`；正式五席維持不變。

## 自動 Loop

正式同步順序是：

1. 偵測並結算新開獎。
2. 重建決策與 Qwen 終局裁決。
3. 先凍結下一期 Qwen／規則／隨機三臂前向 A/B。
4. 再重算本影子研究。

若研究重算失敗，正式下一期登記已完成；背景 watcher 會因研究結果仍舊過期
而在下一輪重試，不會回填或修改已凍結號碼。

## 驗收

```powershell
python -X utf8 council_quality_verify.py
```

這個入口依序跑核心測試、Loop 整合測試、完整 Python 測試、前端
test/lint/build、正式 4,082 期研究、完整後測與 `git diff --check`。

輸出：

- `research/results/council_quality.json`
- `research/results/council_agent_quality.csv`
- `research/results/council_debate_quality.csv`
- `research/results/council_judge_sensitivity.csv`
