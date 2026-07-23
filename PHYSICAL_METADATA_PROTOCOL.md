# 實體開獎中介資料可用性稽核契約

版本：`physical-draw-metadata-availability-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 決策問題

開獎機、開獎球組、落球順序或開獎異常等實體中介資料，是否能在投注截止前
公開取得、以完整歷史重放，並合法用來提高威力彩或大樂透下一期六主號的機率？

本研究是資料與因果資格稽核，不搜尋號碼、不擬合新模型，也不把直播畫面中
事後可見的資訊回填成當期預測特徵。

## 資料來源與 grain

固定檢查以下來源：

1. 專案內 `data/raw/super/*.json` 與 `data/raw/lotto649/*.json` 的官方月回應。
2. 台灣彩券「各期開獎結果資料下載」公開欄位說明。
3. 台灣彩券「開獎流程」與「問與答」對投注截止、設備抽選及轉播時序的說明。
4. 三立《全民 i 彩券》`2026-07-17` 存檔
   `pRQn_EG-AEY` 的一筆人工視覺驗證樣本。

正式預測 grain 固定為 `game + period`。加碼百組百萬、今彩 539、3 星彩、
4 星彩或其他遊戲的機器、球組及畫面不得併入威力彩／大樂透主號資料。

## 官方 raw schema 全量掃描

掃描器必須：

- 讀取兩款遊戲的每一份 JSON 月檔。
- 驗證 root、content、結果陣列、`totalSize` 與列型別。
- 保存檔案數、非空檔案數、列數、唯一期間、日期範圍、row schema variants、
  top-level row keys 與所有 nested key paths。
- 對以下實體欄位同義詞做大小寫不敏感的完整 path 搜尋：
  `machine`、`machine_id`、`draw_machine`、`ball_set`、`ballset`、
  `equipment`、`device`、`studio`、`loading_order`、`drop_order`、
  `anomaly`、`開獎機`、`球組`、`設備`、`落球`、`異常`。
- 任一 JSON 無法解析、schema 錯誤、`totalSize` 不符、重複期別或同一遊戲
  重複日期均 fail closed。

raw schema 找不到實體欄位時，只能得出「官方歷史結果資料沒有保存該欄位」，
不能推論設備不存在或從未更換。

## 公開時間與資料洩漏規則

所有時間使用具時區的 ISO 8601。對目標期 `t`，一筆實體中介資料只有在以下
條件全部成立時，才可成為 ticket-time feature：

1. `game` 與 `period` 唯一且與目標期完全一致。
2. `machine_id`、`ball_set_id` 與其含義經人工複核。
3. `public_observed_at`、`registration_cutoff_at` 皆存在且可解析。
4. `public_observed_at <= registration_cutoff_at`。
5. 來源不是事後剪輯、開獎結果、其他遊戲或加碼活動。
6. 證據影格、影片 ID、影格時間戳及擷取方法完整。

缺任一欄位、時間相等關係無法證明或只知道內部錄影時間，一律
`eligible_for_forecast=false`。內部作業時間不等於公眾可取得時間。

官方 FAQ 所述的每日投注截止時間固定記為 `20:00:00+08:00`；若官方未來
更改規則，必須另開 protocol 版本，不得改寫本 artifact。

## 固定人工樣本

`2026-07-17` 大樂透第 `115000071` 期直播樣本只保存以下可複核事實：

- YouTube 影片 ID：`pRQn_EG-AEY`。
- 直播畫面時間 `20:32:39+08:00` 可見大樂透主獎號開獎機上的標示 `2`。
- 該公開時間晚於 `20:00:00+08:00` 投注截止。
- 畫面沒有提供可可靠辨識並對應此主獎號的球組 ID。

同一影片較早的「端午加碼百組百萬」設備畫面因 grain 不同，固定排除。
本樣本只證明「直播可包含實體資料但時間太晚」，不代表歷史覆蓋率。

## 覆蓋率與模型資格

正式 artifact 必須分開報告：

- 官方 raw API 的機器、球組、落球順序與異常欄位覆蓋率。
- 人工／影片 observation 的遊戲、期別、欄位及時間覆蓋率。
- 投注截止前合格 observation 數與比例。
- 不同遊戲或活動被排除的 observation 數。

要進入下一個實體中介 proper-score protocol，至少必須同時具備：

1. 威力彩與大樂透各至少 104 個依時間先後蒐集、不可回填的目標期。
2. 每款遊戲 `machine_id` 與 `ball_set_id` 完整率皆至少 95%。
3. 每一目標期的設備 assignment 都在該期投注截止前公開。
4. 來源時間與目標期映射 100% 可複核，跨遊戲／活動污染為 0。
5. 候選模型能對所有合法六號集合給出嚴格正值、總和為一的機率。

未達門檻時不得建立設備 Agent、不得更動號碼、不得接入 watcher。
可以建立未來 observation schema，但在時間資格通過前只限事後機制診斷。

## 未來 observation schema

每筆未來資料固定包含：

- `schema_version`
- `game`
- `period`
- `draw_date`
- `registration_cutoff_at`
- `public_observed_at`
- `video_id`
- `archive_url`
- `evidence_frame_timestamp`
- `machine_id`
- `ball_set_id`
- `loading_order`
- `anomaly_flags`
- `source_scope`
- `extraction_method`
- `extraction_confidence`
- `human_verified`
- `eligible_for_forecast`
- `eligibility_reason`

`eligible_for_forecast` 必須由驗證函式依原始欄位重算，不能由人工直接指定。

## 固定決策

若官方 raw API 的實體欄位覆蓋率為零，且沒有投注截止前公開的合格 assignment：

- `status = physical_metadata_unavailable_pre_cutoff`
- `number_probability_model_allowed = false`
- `historical_promotion_eligible = false`
- `watcher_integration_allowed = false`
- `number_changes_allowed = false`
- `future_diagnostic_collection_allowed = true`
- 維持既有 `uniform_null_safe` 完整子集合機率。

## 完整性與測試

1. protocol file SHA-256、protocol payload hash、raw tree hash、records tree hash、
   observation hash 與 artifact hash 必須保存。
2. schema 遞迴掃描、同義詞偵測、時間解析、截止邊界、缺值 fail closed、
   跨遊戲／活動排除及衍生覆蓋率都要有單元測試。
3. 正式 artifact 必須可由本地 raw snapshot 位元級重算。
4. 欄位、時序、結論、來源 hash、records hash 或 artifact hash 任一竄改都必須
   fail closed。
5. 專項測試、完整後端、前端測試、lint、production build、
   `python -m compileall` 與 `git diff --check` 必須通過。
6. `records/`、Agent、既有 7/20／7/21 登記與 watcher 不得由本研究修改。

本研究為純模擬，不構成購買或投注建議。
