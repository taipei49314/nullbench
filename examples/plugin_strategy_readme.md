# Plugin strategies

Also see [plugin_domain_readme.md](plugin_domain_readme.md) for domain packs.

Register a strategy from another package via setuptools entry points.

```toml
# in your package pyproject.toml
[project.entry-points."nullbench.strategies"]
cold = "mypkg.strats:propose_cold"
```

```python
# mypkg/strats.py
from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket

def propose_cold(
    game: GameSpec,
    spec: StrategySpec,
    history: list[Draw],
    period_seed: int,
) -> list[Ticket]:
    ...
```

Then:

```bash
pip install mypkg
nullbench strategies   # shows `cold`
nullbench strategy add cold --study ./my-study --id cold1
```

Contract:

1. Only use `history` draws strictly before the target period (caller enforces cut).
2. Return exactly `spec.tickets_per_period` unique legal tickets.
3. Be deterministic given `(game, spec, history, period_seed)`.
