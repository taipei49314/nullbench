# 終局裁判前向 A/B 預註冊

實驗版本：`final-judge-forward-v1`

## 問題

在相同 15 組開獎前提案、相同 60 次交叉評論與固定五注預算下，
本機 `qwen3:8b` 終局改選是否比可重現規則裁判穩定提高命中？

## 每期三臂

1. `rule_five`：規則裁判選出的五注。
2. `qwen_five`：qwen3:8b 只能從同一批提案改選的五注。
3. `random_five`：同一期固定種子的均勻隨機五注。

三臂必須在目標開獎日 20:30（Asia/Taipei）前寫入
`simulation/forward/ledger.jsonl`。沒有開獎前登記、晚登、Qwen 降級或
模型來源無法驗證的期數，不得補做為有效 Qwen／規則配對。

## 指標與門檻

- 主要指標：每期五注中最佳一注的主號命中數。
- 次要護欄：每期五注總主號命中差不得為負。
- 區間：13 期循環連續區塊 bootstrap 2,000 次。
- 最低樣本：威力彩與大樂透各 52 個合格前向配對。
- 支持門檻：兩款遊戲的 Qwen－規則主要指標 95% 區間下界皆大於 0，
  且兩款遊戲的總主號命中平均差皆不為負。

未達最低樣本一律回報 `collecting_forward_data`。樣本足夠但門檻失敗，
回報 `qwen_advantage_not_supported`；不得挑單一遊戲、單一獎級或事後
更換指標翻案。

## 帳本與自動 loop

`python lotto.py sync` 的順序固定為：

1. 抓取官方當月資料。
2. 結算帳本中已登記且現在已有揭曉的目標期。
3. 產生固定 postmortem，建立嚴格早於下一目標的 13 期回饋。
4. 有新開獎才重建完整逐期 agent loop，並讓 Qwen 讀取已驗證回饋。
5. 從新 manifest 凍結兩款遊戲的下一期三臂。
6. 重建唯讀摘要 `simulation/forward/status.json`。

下一期回饋只含組合層彙總，不含原始開獎號碼或漏號清單；詳細 schema、
來源證明與失敗語意見 [FORWARD_FEEDBACK.md](FORWARD_FEEDBACK.md)。

JSONL 是唯一事實源；`status.json` 只是可重建快照。正式 `records/`、
既有歷史回放 JSONL 與過去決策不得因本實驗改寫。

Qwen 的延遲、降級、Token 與五注分散另由
`final-judge-ops-v1` sidecar 觀測；它不改寫本實驗的主要命中指標、最低樣本或
bootstrap 門檻。詳見 [OPS_TELEMETRY.md](OPS_TELEMETRY.md)。

> 本實驗為純模擬。合法組合的理論開出機率相同，不構成購買或下注建議。
