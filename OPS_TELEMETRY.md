# Qwen 終局裁判運作遙測預註冊

實驗識別：`final-judge-ops-v1`

本規格只回答：「Qwen 終局裁判是否穩定、足夠快，而且其五注組合特徵與開獎後
品質如何？」它不改寫 `final-judge-forward-v1` 的命中指標或 52 期門檻。

## 開獎前保存

每次新的前向登記會同時保存：

- 牆鐘耗時與 Ollama `total/load/prompt_eval/eval` 耗時；
- prompt／輸出 token 數與輸出 token/秒；
- 成功或明確規則降級、錯誤類型；
- 五注來源 Agent 數、單一來源集中度；
- 五注主號聯集大小、兩兩重疊；
- 入選候選的平均評議分數、分歧與規則基準排名。

只有帳本事件含 `ops_experiment_id=final-judge-ops-v1` 才計入。規格建立前的登記
一律列為 `legacy_uninstrumented`，不從日誌或重新呼叫模型補造耗時。

## 運作閘門

兩款遊戲分別取最近 52 次儀器化呼叫，且至少各 10 次才判定：

1. 完整遙測比例至少 90%。
2. 規則降級率不高於 10%。
3. Qwen 牆鐘耗時 p95 不高於 300,000 ms。

未滿 10 次為 `collecting_operational_data`；任一條失敗為
`operationally_degraded`；全部通過才是 `operationally_healthy`。

## 聯合部署閘門

只有原前向實驗已達 `qwen_advantage_supported`，且兩款遊戲的運作閘門皆健康，
才會得到 `eligible_for_qwen_shadow_promotion`。這只允許 Qwen 進入帶規則控制組的
shadow promotion，不會自動刪除規則或均勻隨機對照。

最近 13 個已開獎儀器化樣本會另外顯示 Qwen、規則與均勻隨機五注的平均最佳主號
命中及差值；此移動視窗只作監控，不取代原本 52 期區塊 bootstrap 推論。
