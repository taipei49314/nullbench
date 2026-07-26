import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# --- 需要本機開獎資料快照的測試 ---------------------------------------------
#
# 這個專案是 local-first 研究室:歷史開獎資料由 `python lotto.py ingest` 從官方
# 來源抓下來,落在 `simulation/results/`、`simulation/forward/` 與 `data/raw/`,
# 而這些目錄都被 .gitignore 排除。因此在乾淨 checkout(例如 CI runner)上,
# 底下這些測試會因為找不到資料而失敗 —— 那不是程式壞掉,是前提不成立。
#
# 與其在 CI 設定裡列一長串 --ignore 把它們藏起來,這裡改成「資料不在就明確 skip」。
# 好處是 CI 輸出會誠實顯示「N passed, M skipped」,略過了什麼一目了然;
# 而開發者本機只要跑過 ingest,同一套測試就會完整執行,不需要任何額外參數。
#
# 已知取捨(刻意選的,不是疏忽):
#   跳過的粒度是「整個檔案」,而這 46 個檔案裡其實混著不需要資料、本來就會過的測試。
#   代價是無資料時通過數從 578 掉到 281。
#   曾考慮改成「比對例外訊息,只把缺資料造成的失敗轉成 skip」以保住那 297 個,但那個
#   機制會在測試真的壞掉、而訊息剛好長得像缺資料時把真 bug 吞成 skip —— 寧可少一點
#   覆蓋,也不要一個會說謊的閘門。
#   要拿回覆蓋率,正解是逐一在需要資料的測試上加 `@pytest.mark.needs_snapshot`,
#   讓粒度回到單一測試;那是未來的整理工作,不該用猜測式的字串比對代替。
#
# 維護方式:若新增的測試需要開獎快照,把檔名加進來即可。

SNAPSHOT_PATHS = (
    ROOT / "simulation" / "results",
    ROOT / "data" / "raw",
)

NEEDS_DRAW_SNAPSHOT = frozenset({
    "test_adaptive_special_signal.py",
    "test_agent_ablation.py",
    "test_agent_loop.py",
    "test_calendar_regime_signal.py",
    "test_calendar_regime_signal_verify.py",
    "test_council_quality.py",
    "test_cross_game_overlap_signal.py",
    "test_cross_game_overlap_signal_verify.py",
    "test_debate_confidence.py",
    "test_debate_rank_calibration.py",
    "test_decision_strength.py",
    "test_draw_order_signal.py",
    "test_draw_order_signal_verify.py",
    "test_exact_selector_audit.py",
    "test_forward_lab.py",
    "test_label_signal.py",
    "test_lag_overlap_signal_verify.py",
    "test_max_coverage.py",
    "test_mechanism_agents.py",
    "test_mechanism_signal.py",
    "test_null_safe_probability.py",
    "test_null_safe_probability_verify.py",
    "test_partition_signal.py",
    "test_persistent_bias_signal.py",
    "test_persistent_bias_signal_verify.py",
    "test_physical_metadata_audit.py",
    "test_physical_metadata_audit_verify.py",
    "test_portfolio_coverage.py",
    "test_probability_frontier.py",
    "test_probability_frontier_v2_verify.py",
    "test_probability_frontier_v3_verify.py",
    "test_probability_frontier_v4_verify.py",
    "test_probability_frontier_verify.py",
    "test_probability_stacking.py",
    "test_profit_probability.py",
    "test_profit_probability_verify.py",
    "test_research_data_quality.py",
    "test_research_strategy_search.py",
    "test_settle_report.py",
    "test_switching_bayes.py",
    "test_switching_bayes_forward.py",
    "test_temporal_stacking_diagnostic.py",
    "test_temporal_stacking_diagnostic_verify.py",
    "test_transition_signal.py",
    "test_unconstrained_profit_optimum.py",
    "test_unconstrained_profit_optimum_verify.py",
})

SKIP_REASON = (
    "需要本機開獎資料快照(simulation/results、data/raw,均為 .gitignore 排除)。"
    "先跑 `python lotto.py ingest` 取得資料後即會執行。"
)


def _snapshot_present():
    """所有快照目錄都要有內容才算資料到位。

    刻意用「全部」而非「任一」:`data/raw` 可能因為部分 ingest 而存在,但真正被大量
    測試讀取的是 `simulation/results`。只要有一個缺,測試就會炸,所以缺一即視為不完整。
    """
    for path in SNAPSHOT_PATHS:
        if not path.is_dir() or not any(path.iterdir()):
            return False
    return True


def pytest_collection_modifyitems(config, items):
    if _snapshot_present():
        return
    skip_marker = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if Path(str(item.fspath)).name in NEEDS_DRAW_SNAPSHOT:
            item.add_marker(skip_marker)
