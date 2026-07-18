"""結算＋報告端到端：用真實歷史週（2026-W28）跑完整流程，驗證冪等與誠實排版。"""
from datetime import date, datetime
from pathlib import Path

import pytest

from engine import report as report_mod
from engine import settle, strategy
from engine.env import Env
from engine.games import SUPER, LOTTO649
from engine.ledger import Ledger, TAIPEI
from engine.picker import GAMES, generate
from engine.store import DrawStore

DATA = Path(__file__).parent.parent / "data"
needs_data = pytest.mark.skipif(not (DATA / "raw").exists(), reason="需要已 ingest 的歷史資料")


@pytest.fixture()
def env(tmp_path):
    e = Env(tmp_path)
    e.store = DrawStore(DATA)  # 帳本在 tmp、開獎資料用真實庫
    return e


@needs_data
def test_settle_e2e_past_week(env):
    now = datetime(2026, 7, 18, 12, 0, tzinfo=TAIPEI)
    generate(env.picks, env.weights, env.store, now, week_id="2026-W28")
    summary = settle.run_settle(env.picks, env.settlements, env.weights,
                                env.store, today=date(2026, 7, 18))
    assert summary["new_draw_events"] == 4  # 每遊戲 2 期
    assert summary["new_weeks"] == 2
    assert summary["invalid_weeks"] == []

    for game in GAMES:
        events = strategy.weight_events(env.weights, game)
        assert len(events) == 1
        e = events[0]
        assert e["burn_in"] is True
        assert e["after"] == strategy.UNIFORM          # burn-in 凍結
        assert set(e["scores"]) == set(strategy.UNIFORM)
        assert all(-0.5 <= s <= 0.5 for s in e["scores"].values())
        assert len(e["null_portfolio_pnl"]) == 200
        assert e["official_cost"] == e["n_draws"] * 5 * (100 if game == SUPER else 50)
        assert e["late"] is True                        # 事後補出 → 不入正式統計

    # 冪等：重跑不重記
    summary2 = settle.run_settle(env.picks, env.settlements, env.weights,
                                 env.store, today=date(2026, 7, 18))
    assert summary2["new_draw_events"] == 0 and summary2["new_weeks"] == 0
    assert env.settlements.verify_chain() and env.weights.verify_chain()


@needs_data
def test_report_after_settle(env):
    now = datetime(2026, 7, 18, 12, 0, tzinfo=TAIPEI)
    generate(env.picks, env.weights, env.store, now, week_id="2026-W28")
    settle.run_settle(env.picks, env.settlements, env.weights, env.store,
                      today=date(2026, 7, 18))
    text = report_mod.build_report(env, "2026-W28", today=date(2026, 7, 18))
    assert text.startswith("# lotto-lab 週報 2026-W28")
    assert "本系統為負期望值之純模擬實驗" in text
    assert "純模擬，不下注" in text
    assert "威力彩" in text and "大樂透" in text
    assert "固定獎級獎金（精確）" in text and "浮動獎級獎金（估計）" in text
    assert "無趨勢隨機漫步" in text
    assert report_mod.lint(text) == []
    path = report_mod.write_report(env, "2026-W28", today=date(2026, 7, 18))
    assert Path(path).exists()


def test_lint_catches_forbidden_words():
    assert report_mod.lint("下期必中大獎") == [(1, "必中")]
    assert report_mod.lint("> [違規敘事，僅供紀錄] 下期必中") == []  # 引用區豁免
    with pytest.raises(report_mod.ReportLintError):
        bad_env = None  # write_report 前先 lint —— 直接驗 lint 路徑即可
        raise report_mod.ReportLintError("含禁用詞")


@needs_data
def test_settle_before_draws_is_noop(env):
    """對未來週出號後立刻 check：什麼都不該發生。"""
    now = datetime(2026, 7, 18, 12, 0, tzinfo=TAIPEI)
    generate(env.picks, env.weights, env.store, now, week_id="2026-W30")
    summary = settle.run_settle(env.picks, env.settlements, env.weights,
                                env.store, today=date(2026, 7, 18))
    assert summary["new_draw_events"] == 0 and summary["new_weeks"] == 0
