# Public prospective studies (M5.4)

Two parallel Taiwan studies, pre-registered before the next draw.
This is **not** M5.5: n=26 has not been looked at; do not claim a completed
prospective experiment.

Local study trees stay on the operator machine (gitignored). This file is the
**public registry**: experiment identity, first freeze hashes, vault receipt
ids. The GitHub commit timestamp on this file is part of the public record;
the trust root for A5 is still the M4 vault.

## Protocol

```bash
nullbench vault init   # once
nullbench init taiwan-super -d taiwan_super -e m5-super-2026 --fetch --max-months 12 --formal --formal-primary random --path ~/nullbench-studies
nullbench strategy add random --study ~/nullbench-studies/taiwan-super --tickets 5 --seed 1
nullbench strategy add frequency --study ~/nullbench-studies/taiwan-super --id frequency --tickets 5 --seed 2
nullbench cycle --study ~/nullbench-studies/taiwan-super

nullbench init taiwan-lotto649 -d taiwan_lotto649 -e m5-lotto649-2026 --fetch --max-months 12 --formal --formal-primary random --path ~/nullbench-studies
nullbench strategy add random --study ~/nullbench-studies/taiwan-lotto649 --tickets 5 --seed 1
nullbench strategy add frequency --study ~/nullbench-studies/taiwan-lotto649 --id frequency --tickets 5 --seed 2
nullbench cycle --study ~/nullbench-studies/taiwan-lotto649
```

Each later period (both studies, one call; a failure in one does not skip
the other):

```bash
# vault for these studies (Windows operator tree):
#   set NULLBENCH_VAULT_DIR=C:\Users\play\Desktop\nullbench-studies\vault
nullbench cycle --vault C:\Users\play\Desktop\nullbench-studies\vault ^
  -s C:\Users\play\Desktop\nullbench-studies\taiwan-super ^
  -s C:\Users\play\Desktop\nullbench-studies\taiwan-lotto649
```

Super Lotto typically draws Mon/Thu 20:30 Asia/Taipei; Lotto 649 Tue/Fri.
Run after the official result is posted, not before.

`--max-months` means the **most recent** N months, including the current
month. The first `cycle` with no `--max-months` refreshes the full cache
(past months stay cached) so `freeze --next` is the real next official
period. On Windows, `pip install certifi` if ingest fails with
`CERTIFICATE_VERIFY_FAILED`.

Operator tree used for the registry below (not in git):
`C:\Users\play\Desktop\nullbench-studies\` with vault
`C:\Users\play\Desktop\nullbench-studies\vault`.

## Registry (first freeze)

| Study | Domain | Formal | First freeze period | freeze content_hash (random / frequency) | history_hash | vault receipt_id | frozen_at (UTC) | known draws |
|-------|--------|--------|---------------------|------------------------------------------|--------------|------------------|-----------------|-------------|
| `m5-super-2026` | `taiwan_super` | on, primary=`random`, α at n=26/52 | **115000071** | `ad72e29cf3681fc98a05dcb9a7b1037ed801fda51b88f2abafbbe97e2f552659` / `4b2b0c7bc09cfe9b59e2ab0f64e87a0acc34a5cb72d9e6a0926a5c2f16d00886` | `c224d2bb19d3421653bdc3f3f321f602da12446f8c770ef5354338e91667f5f6` | `6d43f44e-469a-481e-8b00-d24a4ea3b4bf` | 2026-09-03T06:41:45Z | 1942 |
| `m5-lotto649-2026` | `taiwan_lotto649` | on, primary=`random`, α at n=26/52 | **115000085** | `049005ed7faa04e946f985c537071ec066834cc8423e983e866022e1525f0b6c` / `2110c5693a429e48ea79b39bcb15bf48b97dd501ed7faced50a6cf45fa7e89f3` | `2ca7b9f21f22642c2a2e5b86e4cd045f700250817277a64c36226e0283593feb` | `29c267c3-1187-4e0d-aad8-d26ca3dc45b8` | 2026-09-03T06:43:34Z | 2166 |

Both freezes: `outcome_hash=null`, `late=false`, semantic audit green, vault
receipt written. Super Lotto typically draws Mon/Thu 20:30 Asia/Taipei;
this freeze landed 2026-09-03 ~14:41 Asia/Taipei, before the Thursday draw.

Strategies (both): `random` (5 tickets, seed 1), `frequency` (5 tickets, seed 2).
Null bank: 200 portfolios, seed 42.

## Claims

Allowed: these freezes are prospective (`outcome_hash` null, period absent
from `draws.jsonl` at freeze time), notarized to a local vault.

Forbidden until M5.5: “completed a real prospective experiment”.
