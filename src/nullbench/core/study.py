"""On-disk study layout."""

from __future__ import annotations

import json
from pathlib import Path

from nullbench.core.ledger import Ledger
from nullbench.core.models import ExperimentSpec


class Study:
    """
    study/
      experiment.json
      data/draws.jsonl
      ledger/events.jsonl
      reports/
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.experiment_path = self.root / "experiment.json"
        self.data_dir = self.root / "data"
        self.draws_path = self.data_dir / "draws.jsonl"
        self.ledger_path = self.root / "ledger" / "events.jsonl"
        self.reports_dir = self.root / "reports"

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def save_experiment(self, spec: ExperimentSpec) -> None:
        self.ensure_layout()
        self.experiment_path.write_text(
            spec.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load_experiment(self) -> ExperimentSpec:
        if not self.experiment_path.exists():
            raise FileNotFoundError(f"no experiment.json in {self.root}")
        return ExperimentSpec.model_validate_json(
            self.experiment_path.read_text(encoding="utf-8")
        )

    def ledger(self) -> Ledger:
        self.ensure_layout()
        return Ledger(self.ledger_path)

    def exists(self) -> bool:
        return self.experiment_path.exists()
