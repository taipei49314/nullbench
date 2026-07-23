# 威力彩共同第二區自適應訊號預註冊

實驗版本：`adaptive-profit-common-special-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

在 `guarded_profit` 與 `unconstrained_profit` 的主號結構、五注成本及當期
Agent 辯論排序完全不變時，共同第二區若只使用開獎前可見的歷史資料自適應，
能否比「當期辯論支持最高的 coverage 第二區」提高五注嚴格獲利事件率？

## 資料與時間界線

- 來源：`simulation/results/super.jsonl`。
- 粒度：每期威力彩一列；期別與日期必須唯一、合法且依時間排序。
- 暖機：最早 60 期。
- 暖機後前 70% 為 development，後 30% 為外層 holdout。
- Development 再以前 70% 作 inner train、後 30% 作 inner validation。
- 每期預測只能讀取嚴格早於該期的第二區；自適應演算法可以在固定規則下
  使用先前已揭曉期數更新狀態。
- Inner validation 沒有合格候選時，外層 holdout 不開封。

## 凍結候選家族

候選總數固定為七個，之後不得依結果增加或刪除：

1. `expanding_global`：全部過去期數的第二區最高頻值。
2. `expanding_weekday`：過去相同星期的最高頻值；相同星期不足 52 期時
   回退 `expanding_global`。
3. `rolling_52`：最近 52 期最高頻值。
4. `rolling_104`：最近 104 期最高頻值。
5. `rolling_208`：最近 208 期最高頻值。
6. `ewma_half_life_52`：全部過去期數，以 52 期半衰期加權。
7. `ewma_half_life_104`：全部過去期數，以 104 期半衰期加權。

所有同分都選較小第二區，禁止亂數或事後改 tie-break。

## Inner validation 選模

每個候選都和同一期辯論 baseline 作 paired replay。候選必須同時：

- 第二區命中率高於公平模型 `1/8`。
- `guarded_profit` 嚴格獲利事件差大於 0。
- `unconstrained_profit` 嚴格獲利事件差大於 0。

合格者依下列固定順序選唯一方法：

1. 兩種結構嚴格獲利差的較小值最大。
2. 兩種結構嚴格獲利差平均最大。
3. 兩種結構壓力淨額差平均最大。
4. 方法 ID 字典序較小。

沒有合格者時結論為 `no_inner_validation_candidate`，不得查看或建立外層
策略結果。

## 外層門檻

只有 inner validation 入選方法可進入外層 holdout。固定檢查：

- 第二區命中相對公平模型 `1/8` 的精確單尾 p。
- 兩種結構中，候選勝／baseline 勝 discordant pairs 的精確單尾 sign p。
- 上述三項 p 使用 Holm family-wise correction。
- 兩種結構的 13 期 moving-block bootstrap 95% 區間下界皆大於 0。
- 兩種結構的 holdout 前後半嚴格獲利差皆不小於 0。
- 兩種結構平均歷史最低實領壓力淨額差皆不小於 0。

全部通過才可建立 `adaptive-profit-common-special-forward-shadow-v2`。
完整歷史已被其他研究使用，因此即使通過，也只能建立未來不可回填的
shadow；不能直接替換現行號碼或 `profit-common-special-forward-shadow-v1`。

## 固定成本與證明

- 五注成本：NT$500。
- 壓力實領表：沿用 `profit-portfolio-forward-shadows-v1` 截至
  `2026-07-17` 的凍結 snapshot。
- Guarded proof：
  `b91fb1e1f4a4f7ba6478389b05182761472fcdc9784460967b9011a739356ee4`。
- Unconstrained proof：
  `9fa8d7949ce75887af774e664ef913392d723eb58c5bacab1e47e50838216acb`。
- 研究不得修改 `records/`、既有前向 ledger 或任何已登記號碼。

本研究為純模擬。所有合法號碼標籤在公平模型下的理論開出機率相同。
