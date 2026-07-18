"""前向 A/B 一鍵驗收入口測試。"""
from copy import deepcopy

import pytest

import forward_verify


def _valid_result():
    return {
        "registrations": {
            "super": {
                "status": "created",
                "registration_hash": "super-sha",
            },
            "lotto649": {
                "status": "existing",
                "registration_hash": "lotto-sha",
            },
        },
        "summary": {
            "evidence_status": "collecting_forward_data",
            "verification": {
                "chain_valid": True,
                "registrations": 2,
            },
            "games": {"super": {}, "lotto649": {}},
        },
    }


def test_stage_commands_cover_core_and_sync_tests():
    commands = forward_verify.stage_test_commands("python")
    assert [stage for stage, _ in commands] == [
        "forward_core",
        "sync_integration",
    ]
    assert all(command[:6] == [
        "python",
        "-B",
        "-X",
        "utf8",
        "-m",
        "pytest",
    ] for _, command in commands)


def test_run_resolves_platform_launcher(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        forward_verify.shutil,
        "which",
        lambda executable: "C:/tools/npm.cmd",
    )
    monkeypatch.setattr(
        forward_verify.subprocess,
        "run",
        lambda command, **kwargs: captured.update(
            {"command": command, **kwargs}
        ),
    )

    forward_verify._run(["npm", "test"], cwd=tmp_path)

    assert captured == {
        "command": ["C:/tools/npm.cmd", "test"],
        "cwd": tmp_path,
        "check": True,
    }


def test_formal_forward_result_requires_chain_and_both_games():
    forward_verify.verify_forward_result(_valid_result())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result["summary"]["verification"].update(
            {"chain_valid": False}
        ),
        lambda result: result["summary"]["verification"].update(
            {"registrations": 1}
        ),
        lambda result: result.update({"registrations": {}}),
        lambda result: result["summary"].update(
            {"evidence_status": "unknown"}
        ),
        lambda result: result["summary"].update({"games": {}}),
    ],
)
def test_formal_forward_result_rejects_missing_evidence(mutation):
    result = deepcopy(_valid_result())
    mutation(result)
    with pytest.raises(RuntimeError, match="前向終局裁判 A/B 驗收失敗"):
        forward_verify.verify_forward_result(result)
