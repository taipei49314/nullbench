# 完整六主號機率模型前緣 v4 稽核契約

版本：`main-subset-probability-frontier-v4`

凍結日期：`2026-07-19`（Asia/Taipei）

## 目的與固定來源

在 immutable v3 的 13 個完整六主號 proper-score 方法之外，無條件加入
`CROSS_GAME_OVERLAP_PROTOCOL.md` 唯一指定的
`cross_game_overlap_dirichlet_null_1`，建立 14 方法前緣。納入不依候選
結果方向；v1–v3 artifact、audit hash、排名與文件不得改寫。

固定來源：

- `research/results/probability_frontier_v3.json`
- `research/results/cross_game_overlap_signal.json`

兩個來源必須各自通過正式契約，且兩款遊戲期數、首末日期、ledger hash 與
`records/` hash 一致。

## 相同量尺

沿用 v3 的 13 個方法，再加入跨遊戲 overlap raw prequential 模型。每個方法
都必須在 reveal 前對全部合法無序六主號集合形成正規化機率，並使用：

`候選 negative log probability - 精確均勻 negative log probability`

單位 `nats／期`。跨遊戲固定計算等權平均 regret、minimax regret、
`exp(-minimax regret)`、均勻 dominance、雙遊戲負 regret 與雙遊戲
bootstrap 上界是否為負。

排名固定依序為：

1. minimax regret 升冪。
2. 跨遊戲平均 regret 升冪。
3. method ID 字典序。

## 固定排除與決策

排除 marginal mass、top-k、票券命中、任一獎、獲利、效用、第二區、
特別號，以及任何事後球號轉移、lag、日期窗口或 prior 搜尋。

只有非均勻方法同時滿足兩款平均 regret `<0` 且兩款 bootstrap 95% 上界
`<0`，才標為歷史同量尺支持；仍不得直接 promotion。

若沒有方法通過：

- champion 維持 `uniform_null_safe`。
- 不修改 Agent、watcher、records 或既有前向登記。
- 停止用同一歷史搜尋跨遊戲轉移或 overlap 變體。
- 只接受開獎前封存、不可回填的未來完整 subset proper score。

## 完整性與測試

1. 兩個來源 file SHA-256、canonical payload、audit hash、protocol hash 與
   v4 artifact hash 全部保存。
2. 14 個 method ID 唯一，兩款遊戲欄位完整且有限。
3. v3 的 13 列除來源映射外，分數、區間與衍生值逐欄相同。
4. 跨遊戲列逐欄等於正式 diagnostics。
5. 排名、dominance、champion、best non-uniform 與結論可決定性重算。
6. 來源、hash、排名、結論、records 或 artifact 竄改 fail closed。
7. Python 3.11／3.12 artifact 位元級一致。
8. 專項、完整後端、前端、lint、production build 與 `git diff --check`
   全部通過。

本稽核為純模擬，不構成購買或下注建議。
