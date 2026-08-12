# Plugin domains

Register a domain pack from another package via setuptools entry points
(symmetric to strategies).

```toml
# in your package pyproject.toml
[project.entry-points."nullbench.domains"]
mygame = "mypkg.domains.mygame"
```

```python
# mypkg/domains/mygame.py
from nullbench.core.models import GameSpec, SpecialMode

DOMAIN_ID = "mygame"
NETWORK = False  # True if prepare_data hits the network

GAME = GameSpec(
    id="mygame",
    name="My Game",
    main_count=6,
    main_max=49,
    special_mode=SpecialMode.NONE,
    ticket_cost=50.0,
    prize_table={"3": 400.0, "4": 2000.0},
    description="Example plugin domain",
)

def write_demo_data(path, n=120, seed=2026):
    """Optional offline bootstrap used by nullbench init."""
    ...
```

Or expose a factory:

```toml
[project.entry-points."nullbench.domains"]
mygame = "mypkg.domains:build_mygame"
```

```python
def build_mygame():
    return sys.modules[__name__]  # module with GAME + DOMAIN_ID
```

Then:

```bash
pip install mypkg
nullbench domains -v    # shows mygame [plugin]
nullbench init s1 -d mygame
```

## Contract

| Attribute | Required | Notes |
|-----------|----------|-------|
| `DOMAIN_ID` | yes (or entry name) | Registry key |
| `GAME` | yes | `GameSpec` |
| `write_demo_data(path, n=, seed=)` | offline | Called on `init` when no `prepare_data` |
| `prepare_data(data_dir, max_months=)` | network | Called on `init --fetch` / `ingest` |
| `NETWORK` | optional | Defaults to `hasattr(prepare_data)` |

Built-in ids always win on collision.
