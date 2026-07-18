"""執行環境：路徑與帳本的組裝點（唯一知道檔案佈局的地方）。"""
from __future__ import annotations

from pathlib import Path

from .ledger import Ledger
from .store import DrawStore

BASE = Path(__file__).resolve().parent.parent


class Env:
    def __init__(self, base: Path | None = None):
        self.base = base or BASE
        self.data_dir = self.base / "data"
        self.records = self.base / "records"
        self.reports_dir = self.records / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.picks = Ledger(self.records / "picks.jsonl")
        self.settlements = Ledger(self.records / "settlements.jsonl")
        self.weights = Ledger(self.records / "weights.jsonl")
        self.commentary = Ledger(self.records / "commentary.jsonl")
        self.store = DrawStore(self.data_dir)
