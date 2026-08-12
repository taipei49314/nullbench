"""Taiwan Super Lotto 638 (威力彩) domain pack."""

from __future__ import annotations

from pathlib import Path

from nullbench.core.models import GameSpec, SpecialMode
from nullbench.domains import taiwan_fetch

DOMAIN_ID = "taiwan_super"
GAME_KEY = "super"

# Fixed tiers only — floating jackpots valued at 0 (conservative; no jackpot inflation).
GAME = GameSpec(
    id="taiwan_super",
    name="台灣威力彩",
    main_count=6,
    main_max=38,
    special_max=8,
    special_mode=SpecialMode.SEPARATE,
    ticket_cost=100.0,
    prize_table={
        "6+s": 0.0,  # floating — excluded from default valuation
        "6": 0.0,  # floating
        "5+s": 150_000.0,
        "5": 20_000.0,
        "4+s": 4_000.0,
        "4": 800.0,
        "3+s": 400.0,
        "2+s": 200.0,
        "3": 100.0,
        "1+s": 100.0,
    },
    description=(
        "Taiwan Super Lotto (威力彩). Official API history. "
        "Floating jackpot tiers score as 0 by default (conservative). "
        "Pure simulation — no real-money wagering."
    ),
)


def prepare_data(study_data_dir: Path, *, max_months: int | None = None) -> int:
    """Ingest API cache into study data/draws.jsonl. Returns draw count."""
    cache = study_data_dir / "cache"
    taiwan_fetch.ingest(GAME_KEY, cache, max_months=max_months)
    taiwan_fetch.write_cache_provenance(cache, GAME_KEY)
    draws = taiwan_fetch.load_all_draws(GAME_KEY, cache)
    taiwan_fetch.write_draws_jsonl(draws, study_data_dir / "draws.jsonl")
    return len(draws)
