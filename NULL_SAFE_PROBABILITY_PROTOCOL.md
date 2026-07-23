# 公平零模型安全機率閘門預註冊

研究版本：`null-safe-probability-gate-v1`

未來候選版本：`null-safe-probability-forward-shadow-v1`

前向登記版本：`null-safe-probability-shadow-forward-v7`

前向評分膠囊：`null-safe-probability-score-capsule-v1`

前向狀態版本：`null-safe-probability-forward-state-v1`

證據程序：`restart-mixture-e-process-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題與成功定義

現行七專家 probability stacking 已把均勻專家權重提高到 99.999% 以上，
但仍留下極小的非均勻質量；完整歷史三個 proper-score 維度因此都略差於
精確均勻基準。

本候選不嘗試從同一份歷史再找號碼規則。成功定義是：

1. 沒有充分、開獎前可得的非均勻 likelihood 證據時，預測分布精確等於
   公平零模型。
2. 只有固定證據門檻被跨越後，下一期才允許使用非均勻 stacking 分布。
3. 歷史只初始化閘門；策略升級仍只接受新 experiment ID 下不可回填的
   未來 proper score。

## 完整六號子集 likelihood

主號分布 `p_1 ... p_N` 先轉成合法的無序六號子集機率：

`P(S) = product(p_i for i in S) / e_6(p_1 ... p_N)`

其中 `e_6` 是第六階 elementary symmetric polynomial。它會對全部合法
六號子集正規化為 1；若每個 `p_i = 1/N`，每個子集機率精確等於
`1 / C(N,6)`。

每期主號 log likelihood ratio 是：

`log LR_t = log P_model(S_t) - log P_uniform(S_t)`

威力彩第二區則使用：

`log LR_t = log(p_t(actual) / (1/8))`

這比把六個主號當成獨立抽樣更符合不重複開獎機制。

## 可重啟 mixture e-process

為了讓很晚才出現的訊號仍可被偵測，每一期 `s` 都建立一個從該期開始的
likelihood-ratio component，固定起始權重：

`w_s = 6 / (pi^2 × s^2)`

所有權重總和為 1。第 `t` 期揭曉後：

`E_t = sum(w_s × product(LR_u, u=s..t), s<=t) + sum(w_s, s>t)`

實作用精確遞迴，每期 O(1)，完整回放 O(draws)，不保留 O(draws²) 狀態。
第 `t` 期的 forecast 只讀 `E_(t-1)`；當期揭曉只更新下一期。

## 固定多重證據門檻

證據 family 固定為三個 stream：

- 威力彩主號
- 威力彩第二區
- 大樂透主號

family alpha 固定為 `0.05`，平均分配後每 stream alpha 為 `0.05 / 3`，
因此每個 stream 的啟用門檻固定為：

`E >= 1 / (0.05/3) = 60`

門檻不是根據歷史最大值調整。描述性敏感度只檢查 `3／20／60`，不得用來
更換正式門檻。

## 閘門關閉時的決策

- 主號完整機率：精確均勻。
- 威力彩第二區完整機率：精確均勻。
- 五注標籤與分組：沿用已驗證的 consensus coverage。
- 五注成本、30 號聯集、兩兩互斥與五個不同第二區不變。

這避免均勻機率發生大量同分時，因自然排序任意選成 `1–30`；沒有機率證據
時，候選不聲稱 coverage 標籤較可能，只保留其既有結構與辯論代表性。

## 閘門開啟時的決策

只有對應維度在目標期前已達 `E >= 60` 時，該維度才使用當時七專家
prequential stacking 分布。主號啟用後取機率前 30 名並分成五注互斥結構；
第二區獨立依自己的閘門決定是否使用 stacking 排序。

閘門狀態、來源 ledger hash、fitted-through、完整模型權重、protocol hash
與 candidate hash 都必須可重算。

## 歷史用途限制

完整歷史已被多項研究使用，因此以下結果只有描述性作用：

- 驗證子集 likelihood 與 e-process 方向。
- 初始化下一個 future-only candidate 的模型權重與 gate state。
- 確認新規則在公平零模型沒有證據時會回退均勻。

不得把歷史 regret 歸零寫成「未來已證明提高」，也不得回填既有 7/20、
7/21 登記。第一次確認性證據必須來自新 experiment ID 開獎前已凍結的
完整機率分布。

## 自動前向交易

背景 loop 的順序固定為：

1. 先結算已存在且已揭曉的舊登記。
2. 重建完整 agent replay 與 stacking candidate。
3. 更新 `null_safe_probability_forward.json`：複製同一期 stacking
   candidate 的 fitted-through、source ledger hash 及主號／第二區權重；
   e-process state 每次從凍結正式基線開始，只依序接受帳本中開獎前已
   登記的全部 v7 proper-score 結算。v6 或更早版本的空窗只前移資料時間
   邊界，不得推進 gate；重跑與晚到的合法 v7 結算不得重複或漏算。
4. 驗證 operational candidate 與 stacking candidate 的時間、來源與權重
   完全一致，並驗證每筆 v7 transition 的 prior state 連續且只能套用一次。
5. 只為更晚的新目標期建立 v7 登記；同一期已有 v6 或更早登記時冪等 no-op。
6. v7 capsule 封存安全分布、未開牌證據分布與 prior state。揭曉後安全
   分布計分，證據 LR 更新 next state；結算摘要不保存原始開獎號碼。

任一步失敗就停止該次新目標登記，由下一輪重試，不降級成未驗證的機率偏移。

## Fail-closed

- ledger hash、事件鏈、期別順序、decision hash、15 組提案、60 次評論或
  15 個 candidate score 任一不符即拒絕。
- 主號分布、第二區分布、子集 likelihood 或 e-process state 無法正規化、
  含非有限值或不能重建即拒絕。
- fitted-through 不得等於或晚於目標期。
- candidate、gate state、完整機率、票組與 support evidence 任一 hash
  不符即拒絕。
- 閘門未啟用時不得以非均勻機率冒充成功，也不得把同分自然排序解釋成
  號碼優勢。

本系統為純模擬。公平開獎下合法組合的理論機率相同，不構成購買或下注建議。
