# 實體開獎中介資料可用性稽核

正式實驗：`physical-draw-metadata-availability-audit-v1`

## 結論

目前公開資料不能把開獎機、球組或落球順序合法用於當期選號，正式機率維持
`uniform_null_safe`。

原因不是「設備一定沒有偏差」，而是當期設備 assignment 沒有在投注截止前
公開。若把 20:30 後直播看到的機器標示回填成 20:00 前的預測特徵，就是明確
的資料洩漏。

正式決策：

- 不建立實體設備 Agent 或機器條件式號碼模型。
- 不改威力彩／大樂透號碼，不接入 watcher。
- 可以從現在起蒐集影像 observation，但在公開時間資格通過前只限事後機制診斷。
- 即使日後有完整歷史，也必須另開 future-only proper-score protocol，不能用
  本次單一樣本直接 promotion。

## 官方 raw schema 全量結果

掃描 `data/raw/super/*.json` 與 `data/raw/lotto649/*.json` 的每一份官方月回應，
遞迴列出所有 top-level 與 nested key paths，並搜尋 protocol 凍結的實體欄位
同義詞。

| 遊戲 | 月檔 | 非空／空檔 | 正式期數 | 日期 | 實體欄位期數 |
| --- | ---: | ---: | ---: | --- | ---: |
| 威力彩 | 223 | 223／0 | 1,929 | 2008-01-24～2026-07-16 | 0 |
| 大樂透 | 271 | 235／36 | 2,153 | 2007-01-02～2026-07-17 | 0 |
| 合計 | 494 | 458／36 | 4,082 | — | 0 |

兩款遊戲的 `game + period` 與日期都唯一，重複期別、重複日期、JSON／root／
content schema 錯誤及 `totalSize` 不符均為 0。

官方 raw 列只有：

- 期別、開獎日、兌獎日。
- 排序獎號 `drawNumberSize` 與抽出順序 `drawNumberAppear`。
- 銷售額、總獎金與各獎級派彩物件。

全部 4,082 期都沒有 machine、ball set、equipment、studio、loading order、
anomaly 或其凍結同義詞，實體 metadata 覆蓋率為 `0%`。台灣彩券的
[各期結果下載頁](https://www.taiwanlottery.com/lotto/history/result_download/)
所列欄位同樣只有遊戲、期別、日期、銷售、獎金、六主號與特別號，沒有設備 ID。

這只能證明官方結果資料未保存設備欄位，不能推論設備不存在。

## 公開時間因果稽核

台灣彩券[開獎流程](https://www.taiwanlottery.com/run_lottery/info/)說明：
投注截止後才進行開獎作業，開獎來賓會抽選開獎機、球組與落球順序，之後才開始
開獎實況錄影。

台灣彩券[問與答](https://www.taiwanlottery.com/customer_service/faq/)另明載：
投注於 20:00 截止，正式開獎為 20:30；中間 30 分鐘供主電腦中心統計當期銷售，
而電視採重點式轉播，不是全部流程連續公開。

固定人工樣本為三立 `2026-07-17` 存檔：

- archive：
  [全民 i 彩券 2026-07-17](https://d25vj0wbzayc6h.cloudfront.net/Live/3763/24003)
- YouTube ID：`pRQn_EG-AEY`
- 大樂透期別：`115000071`
- 投注截止：`20:00:00+08:00`
- 主獎號機器標示 `2` 可見時間：`20:32:39+08:00`
- 晚於截止：`1,959` 秒，即 32 分 39 秒
- 可可靠對應此主獎號的球組 ID：缺失

影片稍早的「端午加碼百組百萬」機器／球組畫面屬不同抽獎 grain，已固定排除，
不拿來補大樂透主號欄位。

## 覆蓋與模型資格

| 指標 | 威力彩 | 大樂透 |
| --- | ---: | ---: |
| 歷史正式期數 | 1,929 | 2,153 |
| 人工驗證 observation | 0 | 1 |
| period 覆蓋率 | 0% | 0.04645% |
| machine ID 完整率 | 0% | 100% |
| ball-set ID 完整率 | 0% | 0% |
| 投注截止前合格 observation | 0 | 0 |

下一個實體中介模型至少需要兩款遊戲各 104 個不可回填的 future 期數、
machine 與 ball-set 完整率各 95% 以上，且每期 assignment 都必須在該期
投注截止前公開。目前所有關鍵門檻都未通過。

即使未來能從影片重建大量歷史設備 ID，只要當期 assignment 仍在 20:00 後才
公開，它仍不能改善可購買票券的當期條件機率；最多只能檢查設備是否存在事後
可辨識的物理差異。

## 未來蒐集規格

正式 schema 保存 game、period、draw date、registration cutoff、
public observed time、影片與 archive ID、證據影格、machine ID、ball-set ID、
loading order、異常旗標、來源 scope、擷取方法／信心與人工複核。

`eligible_for_forecast` 不接受人工直接填值，必須由程式依下列條件重算：

`public_observed_at <= registration_cutoff_at`

且來源必須是同一 game／period 的主獎號、machine 與 ball-set 皆存在、經人工
複核。時間缺失、無時區、其他遊戲、加碼活動或事後影片一律 fail closed。

## 執行、測試與完整性

```powershell
python -B -X utf8 physical_metadata_audit.py
python -B -X utf8 physical_metadata_audit_verify.py --tests-only
```

正式 artifact：`research/results/physical_metadata_audit.json`

- schema 遞迴掃描、同義詞折疊、時間邊界、缺值、跨 scope、live recompute、
  竄改與 cp1252 專項測試：17／17。
- 完整後端回歸：653／653；前端：22／22；ESLint、production build、
  Python compile 與 `git diff --check` 全部通過。
- artifact SHA-256：
  `c8def51f0266b8265b45c1921b43cd870d8e5508f8a12b5da353dd47dda955c4`
- audit hash：
  `2824c55f71137b85800ac48093175d45e7aa60307b49e21671e99bdf05c43d29`
- protocol file SHA-256：
  `73460f6bab690fde261b0a88f671c3a733d161c3ace945a875b8cb089c05665a`
- protocol payload hash：
  `d180c6299a4186bb5b5103c3529590802ab16051ef6314ed43b9196d9088af2a`
- source evidence hash：
  `9b45f30dbaae464c8ca241eeb68f2c9acd91172b6a2e43bd71ec71fb2f3c0e42`
- `records/` 維持
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

完整判定規格見 `PHYSICAL_METADATA_PROTOCOL.md`。本研究為純模擬，不構成購買
或投注建議。
