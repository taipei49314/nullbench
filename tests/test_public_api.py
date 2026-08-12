"""Public API / maturity smoke for open-source product surface."""

from __future__ import annotations

from nullbench import (
    __version__,
    add_strategy,
    build_report,
    freeze_latest,
    freeze_period,
    init_study,
    settle_period,
)
from nullbench.maturity import LEVELS, describe


def test_public_exports_present() -> None:
    assert callable(init_study)
    assert callable(add_strategy)
    assert callable(freeze_period)
    assert callable(freeze_latest)
    assert callable(settle_period)
    assert callable(build_report)
    assert __version__


def test_maturity_m2_frozen() -> None:
    status = describe()
    by_id = {row["id"]: row for row in status.levels}
    assert by_id["M1"]["role"] == "done"
    assert by_id["M2"]["role"] == "frozen"
    assert by_id["M3"]["role"] == "partial"
    assert LEVELS[2][0] == "M2"
