"""Taiwan Lotto 649 (大樂透) domain pack."""

from __future__ import annotations

from pathlib import Path

from nullbench.core.models import GameSpec, SpecialMode
from nullbench.domains import taiwan_fetch

DOMAIN_ID = "taiwan_lotto649"
GAME_KEY = "lotto649"

# Fixed tiers only — floating upper tiers at 0.
GAME = GameSpec(
    id="taiwan_lotto649",
    name="台灣大樂透",
    main_count=6,
    main_max=49,
    special_max=None,
    special_mode=SpecialMode.FROM_MAIN_POOL,
    ticket_cost=50.0,
    prize_table={
        "6": 0.0,  # floating jackpot
        "5+s": 0.0,  # floating
        "5": 0.0,  # floating
        "4+s": 0.0,  # floating
        "4": 2_000.0,
        "3+s": 1_000.0,
        "3": 400.0,
        "2+s": 400.0,
    },
    description=(
        "Taiwan Lotto 649 (大樂透). Special ball from main pool; tickets pick 6 mains only. "
        "Floating upper tiers score as 0 by default (conservative). "
        "Pure simulation — no real-money wagering."
    ),
)


def prepare_data(study_data_dir: Path, *, max_months: int | None = None) -> int:
    cache = study_data_dir / "cache"
    taiwan_fetch.ingest(GAME_KEY, cache, max_months=max_months)
    taiwan_fetch.write_cache_provenance(cache, GAME_KEY)
    draws = taiwan_fetch.load_all_draws(GAME_KEY, cache)
    taiwan_fetch.write_draws_jsonl(draws, study_data_dir / "draws.jsonl")
    return len(draws)
