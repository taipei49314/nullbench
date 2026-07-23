# 完整六主號機率模型前緣 v2 稽核契約

版本：`main-subset-probability-frontier-v2`

凍結日期：`2026-07-19`（Asia/Taipei）

## 目的

在 immutable v1 的 11 個完整六主號 proper-score 方法之外，無條件加入
`LAG_OVERLAP_PROTOCOL.md` 預先指定的
`lag_overlap_dirichlet_null_1`，建立 12 方法前緣。是否納入不依該候選結果
方向；v1 artifact、audit hash、排名與文件不得改寫。

## 固定來源

- `research/results/probability_frontier.json`
- `research/results/lag_overlap_signal.json`

v1 必須通過自身正式契約，且包含原本四個 leaf source 的固定 SHA-256。
lag-overlap artifact 必須通過自身正式契約。兩個來源的威力彩／大樂透期數、
首末日期、ledger hash 與 `records/` hash 必須一致。

## 固定方法

沿用 v1 的 11 個方法，再加入：

- `lag_overlap_dirichlet_null_1`：使用 lag-overlap artifact 的 raw
  prequential regret 與 bootstrap 區間。

不另加入 `null_safe_lag_overlap`，因其歷史 gate 從未啟用、分布與
`uniform_null_safe` 完全相同；重複列不提供新模型。

## 相同量尺

每個方法都必須：

1. 在當期 reveal 前建立 forecast。
2. 對全部合法無序六主號集合形成總和為一的正機率分布。
3. 使用
   `候選 negative log probability - 精確均勻 negative log probability`
   的平均值，單位 `nats／期`。
4. 使用同一完整正式歷史；第一期沒有 lag 時，lag-overlap 固定均勻、regret 0。

跨遊戲固定計算：

- `mean_regret_across_games`：兩款平均 regret 的等權平均。
- `minimax_regret`：兩款平均 regret 的較大值。
- `worst_game_probability_ratio_vs_uniform = exp(-minimax_regret)`。
- `strictly_dominated_by_uniform`：兩款 regret 都 `>=0` 且至少一款 `>0`。
- `both_games_mean_negative`。
- `both_games_bootstrap_upper_negative`。

排名固定為：

1. `minimax_regret` 由小到大。
2. `mean_regret_across_games` 由小到大。
3. `method_id` 字典序。

## 固定排除

- 舊 marginal mass loss。
- top-k、票券命中與任一獎事件。
- coverage、獎級、獲利與效用指標。
- 威力彩第二區與大樂透特別號。
- lag-overlap 的 null-safe 重複均勻列。
- 任何事後選擇的窗口、prior、遊戲或欄位。

## 決策規則

只有非均勻方法在兩款遊戲平均 regret 都 `<0`，且兩款 bootstrap 95% 上界
都 `<0`，才能標為「歷史上同量尺優於均勻」。歷史結果仍不得直接 promotion；
只允許另立 future-only experiment。

若無方法通過：

- champion 維持 `uniform_null_safe`。
- 停止在相同歷史上調參。
- 不修改 Agent、watcher、records 或既有前向登記。
- 只等待不可回填的 v7 未來完整 subset proper score。

## 完整性與測試

1. 兩個來源檔 SHA-256、canonical payload hash、來源 audit hash、protocol hash、
   v2 artifact hash 全部固定保存。
2. 12 個 method ID 必須唯一，兩款遊戲欄位完整且有限。
3. v1 的 11 列除 `source_ids` 映射為 v1 聚合來源外，所有分數、區間與衍生值
   必須逐欄相同。
4. lag-overlap 列必須逐欄等於正式 raw diagnostics。
5. 排名、dominance、champion、best non-uniform 與結論必須可由列資料決定性重算。
6. 來源值、hash、排名、結論、records hash 或 artifact hash 竄改必須 fail closed。
7. Python 3.11／3.12 artifact 必須位元級一致。
8. 專項、完整後端、前端、lint、production build 與 `git diff --check` 全通過。

本稽核為純模擬，不構成購買或下注建議。
