# 完整六主號機率模型前緣 v3 稽核契約

版本：`main-subset-probability-frontier-v3`

凍結日期：`2026-07-19`（Asia/Taipei）

## 目的

在 immutable v2 的 12 個完整六主號 proper-score 方法之外，無條件加入
`CALENDAR_REGIME_PROTOCOL.md` 唯一指定的
`weekday_dirichlet_1_regular`，建立 13 方法前緣。納入不依候選結果方向；
v1、v2 artifact、audit hash、排名與文件均不得改寫。

## 固定來源

- `research/results/probability_frontier_v2.json`
- `research/results/calendar_regime_signal.json`

兩個來源必須各自通過正式契約。威力彩／大樂透期數、首末日期、ledger hash
與 `records/` hash 必須一致。

## 相同量尺與固定方法

沿用 v2 的 12 個方法，再加入：

- `weekday_dirichlet_1_regular`：正常開獎日使用截至上一期的同星期球號
  Dirichlet-1 完整 subset 分布；大樂透正常星期外加開固定均勻。

每個方法都必須對全部合法無序六主號集合形成正規化機率，並使用：

`候選 negative log probability - 精確均勻 negative log probability`

單位固定為 `nats／期`。跨遊戲固定計算：

- 兩款平均 regret 的等權平均。
- 兩款 regret 較大值作 minimax regret。
- `exp(-minimax regret)` 作最差遊戲幾何平均機率比。
- 兩款都非負且至少一款正值時，標記為被均勻嚴格支配。
- 兩款平均 regret 都 `<0` 且兩款 bootstrap 95% 上界都 `<0`，才標記為
  歷史同量尺支持。

排名固定為 minimax regret、跨遊戲平均 regret、method ID 依序升冪。

## 固定排除與決策

排除 marginal mass、top-k、票券命中、任一獎、獲利、效用、第二區、特別號
與任何事後月份／節日／prior／窗口搜尋。

若沒有非均勻方法同時通過兩款遊戲門檻：

- champion 維持 `uniform_null_safe`。
- 不修改 Agent、watcher、records 或既有前向登記。
- 停止使用同一歷史調星期、月份、節日或球號 prior。
- 只接受不可回填的未來完整 subset proper score。

歷史結果一律不得直接 promotion。

## 完整性與測試

1. 兩個來源檔 SHA-256、canonical payload、來源 audit hash、protocol hash 與
   v3 artifact hash 全部保存。
2. 13 個 method ID 唯一；兩款遊戲欄位完整且有限。
3. v2 的 12 列除來源映射外，所有分數、區間與衍生值逐欄相同。
4. calendar 列逐欄等於正式 raw diagnostics。
5. 排名、dominance、champion、best non-uniform 與結論可決定性重算。
6. 來源、hash、排名、結論、records 或 artifact 竄改 fail closed。
7. Python 3.11／3.12 artifact 位元級一致。
8. 專項、完整後端、前端、lint、production build 與 `git diff --check`
   全部通過。

本稽核為純模擬，不構成購買或下注建議。
