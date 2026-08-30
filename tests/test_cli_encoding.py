"""CLI output must not crash on legacy, non-UTF-8 terminals."""

from __future__ import annotations

import os
import subprocess
import sys


def test_demo_survives_cp1252_output(tmp_path) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252:strict"
    unicode_root = tmp_path / "測試"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nullbench",
            "demo",
            "--name",
            "encoding-smoke",
            "--path",
            str(unicode_root),
            "--periods",
            "1",
        ],
        capture_output=True,
        check=False,
        encoding="cp1252",
        errors="replace",
        env=env,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "backtest" in result.stdout.lower()
    assert (unicode_root / "encoding-smoke" / "reports" / "latest.md").is_file()
    assert (unicode_root / "encoding-smoke" / "reports" / "latest.html").is_file()
