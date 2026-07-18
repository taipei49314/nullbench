import json

import pytest

from engine.games import LOTTO649, SUPER
from engine.sync_service import compare_draw_counts, sync_latest


def test_compare_draw_counts_detects_only_new_draws():
    assert compare_draw_counts(
        {SUPER: 10, LOTTO649: 20},
        {SUPER: 11, LOTTO649: 20},
    ) == {SUPER: 1, LOTTO649: 0}


def test_compare_draw_counts_fails_closed_on_regression():
    with pytest.raises(ValueError, match="期數倒退"):
        compare_draw_counts(
            {SUPER: 10, LOTTO649: 20},
            {SUPER: 9, LOTTO649: 20},
        )


def _manifest(super_count=10, lotto_count=20):
    def game_payload(count):
        return {
            "draws_replayed": count,
            "last_target": {"date": "2026-07-17", "period": count},
            "next_decision": {
                "target": {"date": "2026-07-20", "period": count + 1}
            },
        }

    return {
        "games": {
            SUPER: game_payload(super_count),
            LOTTO649: game_payload(lotto_count),
        },
        "manifest_hash": "verified-hash",
    }


def test_sync_rebuilds_only_when_new_draws_exist(tmp_path, monkeypatch):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(_manifest()), encoding="utf-8"
    )

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 11, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)
    phases = []
    runner_calls = []

    def runner(store, output_dir):
        runner_calls.append((store, output_dir))
        return _manifest(11, 20)

    result = sync_latest(
        tmp_path,
        fetcher=lambda game, data_dir: (1, 1),
        runner=runner,
        progress=lambda phase, message, details: phases.append(phase),
    )

    assert result["regenerated"] is True
    assert result["new_draws_total"] == 1
    assert result["games"][SUPER]["new_draws"] == 1
    assert len(runner_calls) == 1
    assert phases == ["checking", "reviewing", "optimizing", "ready"]


def test_sync_keeps_verified_artifacts_when_counts_are_unchanged(
    tmp_path, monkeypatch
):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(_manifest()), encoding="utf-8"
    )

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 10, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)

    def unexpected_runner(store, output_dir):
        raise AssertionError("沒有新開獎時不應重建")

    result = sync_latest(
        tmp_path,
        fetcher=lambda game, data_dir: (1, 1),
        runner=unexpected_runner,
    )

    assert result["regenerated"] is False
    assert result["new_draws_total"] == 0
