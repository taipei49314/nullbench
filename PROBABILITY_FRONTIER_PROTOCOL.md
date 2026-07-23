# 完整六號機率模型前緣稽核契約

版本：`main-subset-probability-frontier-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 決策問題

目前已完成多種歷史研究，但量尺不完全相同。本稽核只回答：

> 在已正式完成、可比較的下一期完整無序六主號 proper-score 模型中，
> 哪一個是雙遊戲 minimax champion？是否有任何非均勻方法同時優於均勻？

本稽核不提出新號碼模型、不重新開封 holdout，也不從結果產生新參數。

## 納入條件

一個方法必須同時滿足：

1. 威力彩與大樂透都有結果。
2. 每期 forecast 嚴格早於該期 reveal。
3. 評分對象是合法、完整、無序的六主號子集合。
4. 模型對全部 `C(N,6)` 合法集合構成正規化正機率分布。
5. 指標是候選 negative log probability 減精確均勻基準 negative log
   probability，單位 `nats／期`；負值才優於均勻。
6. 使用完整正式歷史，威力彩 1,929 期、大樂透 2,153 期，日期與 ledger
   hash 必須一致。
7. 來源是可重算、通過正式 verifier 的 artifact。

固定納入來源：

- `research/results/null_safe_probability.json`
- `research/results/temporal_stacking_diagnostic.json`
- `research/results/draw_order_signal.json`
- `research/results/persistent_bias_signal.json`

`temporal_stacking_diagnostic.json` 的九個主號方法固定納入；第二區 stream
排除。另加入抽出順序與持續球號偏差各一個固定方法，共 11 列。

## 明確排除

- 舊 probability stacking 的 marginal mass loss：不是完整 subset loss。
- Agent、label、partition、transition、confidence 的 top-30、最佳一注、
  任一獎或命中指標：不是完整機率分布 proper score。
- structural、coverage、profit 研究：改善的是五注事件結構或效用，不是
  下一期球號標籤機率。
- 威力彩第二區與大樂透特別號：定義域不同，不與六主號前緣混排。
- 任何事後挑選的窗口、prior、遊戲或欄位。

排除不代表研究無效，只代表不能拿來回答本次「完整六主號機率」問題。

## 固定計算

每個方法保存兩款遊戲各自：

- 平均 regret。
- 95% block-bootstrap 下界與上界。
- `exp(-mean_regret)`：對實際開獎集合所給機率相對均勻的幾何平均倍率。

跨遊戲固定計算：

- `mean_regret_across_games`：兩款遊戲平均 regret 的等權平均。
- `minimax_regret`：兩款遊戲平均 regret 的較大值。
- `worst_game_probability_ratio_vs_uniform = exp(-minimax_regret)`。
- `strictly_dominated_by_uniform`：兩款 regret 都 `>=0`，且至少一款 `>0`。
- `both_games_mean_negative`。
- `both_games_bootstrap_upper_negative`。

排序固定為：

1. `minimax_regret` 由小到大。
2. `mean_regret_across_games` 由小到大。
3. `method_id` 字典序。

Champion 是排序第一名；最佳非均勻方法是排除 `uniform_null_safe` 後第一名。

## 決策規則

- 只有兩款遊戲平均 regret 都 `<0` 且 bootstrap 上界都 `<0` 的非均勻方法，
  才能被標為「歷史上同量尺優於均勻」。
- 即使通過，也不能用重複使用的歷史直接 promotion；只能另立新的
  future-only experiment。
- 若沒有方法通過，正式 champion 維持 `uniform_null_safe`，停止在同一
  歷史上調參找負 regret。
- 不改 Agent、watcher、既有登記或 `records/`。

## 完整性與測試

1. 四個來源檔 SHA-256 必須固定保存並由 verifier 對目前檔案重算。
2. 來源遊戲期數、日期與 ledger hash 必須一致。
3. temporal 的 `uniform` 必須精確為 0，且 current mixture 必須與
   null-safe artifact 的 operational comparison 一致。
4. 11 個 method ID 必須唯一，兩款遊戲欄位完整且數值有限。
5. 排名、dominance、champion、best non-uniform 與結論必須可由列資料
   決定性重算。
6. 來源值、量尺、排名、decision、records hash 或 artifact hash 竄改必須
   fail-closed。
7. 專項測試、完整後端、前端測試、lint 與 production build 全部通過。

本稽核為純模擬，不構成購買或下注建議。
