"""Semantic integrity — hash seals beyond append-only chain.

Hash chains alone cannot stop a full-file rewrite with re-linked hashes
(IC-01). Seals bind freezes to experiment, history, code, and (when known)
outcomes; settle recomputes payouts; report prefers sealed settle draws.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

from nullbench.core.hashing import canonical_json, content_hash, sha256_hex
from nullbench.core.models import Draw, ExperimentSpec, Ticket
from nullbench.errors import IntegrityError


def draw_order_key(d: Draw) -> tuple[str, str]:
    """Stable causal order: date then period id (never raw file order)."""
    return (d.date or "", d.period)


def order_draws(draws: list[Draw]) -> list[Draw]:
    return sorted(draws, key=draw_order_key)


def history_before(draws: list[Draw], period: str) -> list[Draw]:
    """All draws strictly before ``period`` in stable order (IC-04)."""
    ordered = order_draws(draws)
    targets = [d for d in ordered if d.period == period]
    if not targets:
        return []
    tkey = draw_order_key(targets[0])
    return [d for d in ordered if draw_order_key(d) < tkey]


def draw_payload(d: Draw) -> dict[str, Any]:
    return {
        "period": d.period,
        "numbers": list(d.numbers),
        "special": d.special,
        "date": d.date,
    }


def history_hash(history: list[Draw]) -> str:
    payload = [draw_payload(d) for d in order_draws(history)]
    return content_hash({"history": payload})


def experiment_hash(spec: ExperimentSpec) -> str:
    """Seal of experiment parameters that must not change after freeze (IC-05)."""
    body = spec.model_dump(mode="json")
    # stable subset — full dump is fine if sorted
    return content_hash({"experiment": body})


def freeze_content_payload(
    *,
    experiment_id: str,
    period: str,
    strategy_id: str,
    tickets: list[Ticket] | list[dict],
    experiment_hash_: str,
    history_hash_: str,
    code_fingerprint_: str,
    outcome_hash: str | None,
) -> dict[str, Any]:
    tix = [
        t.model_dump() if isinstance(t, Ticket) else t
        for t in tickets
    ]
    return {
        "experiment_id": experiment_id,
        "period": period,
        "strategy_id": strategy_id,
        "tickets": tix,
        "experiment_hash": experiment_hash_,
        "history_hash": history_hash_,
        "code_fingerprint": code_fingerprint_,
        "outcome_hash": outcome_hash,
    }


def freeze_content_hash(**kwargs: Any) -> str:
    return content_hash(freeze_content_payload(**kwargs))


def outcome_hash(draw: Draw) -> str:
    return content_hash({"outcome": draw_payload(draw)})


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def source_fingerprint(obj: Any) -> str:
    """Hash callable/module source when available (IC-08)."""
    try:
        src = inspect.getsource(obj)
    except (OSError, TypeError):
        try:
            mod = inspect.getmodule(obj)
            if mod and getattr(mod, "__file__", None):
                p = Path(mod.__file__)
                if p.exists() and p.suffix == ".py":
                    return sha256_hex(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
        return sha256_hex(repr(obj))
    return sha256_hex(src)


def code_fingerprint(
    *,
    strategy_kinds: list[str],
    domain_id: str,
) -> str:
    """Bind package version + strategy implementations + domain module (IC-08)."""
    from nullbench import __version__
    from nullbench.domains import get_domain
    from nullbench.strategies import get_strategy

    parts: dict[str, str] = {"nullbench": __version__}
    for kind in sorted(set(strategy_kinds)):
        fn = get_strategy(kind)
        parts[f"strategy:{kind}"] = source_fingerprint(fn)
    try:
        mod = get_domain(domain_id)
        parts[f"domain:{domain_id}"] = source_fingerprint(mod)
        game = getattr(mod, "GAME", None)
        if game is not None:
            parts[f"game:{domain_id}"] = content_hash(game.model_dump(mode="json"))
    except Exception as e:
        parts[f"domain:{domain_id}"] = sha256_hex(f"err:{e}")
    return content_hash(parts)[:32]


def require_freeze_seals(row: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """M1 freezes must carry non-empty experiment/history/code seals (R-02).

    Empty-string seals previously skipped settle drift checks (`if eh and …`),
    allowing experiment.json edits after clearing the hash field.
    """
    meta = row.get("meta") or {}
    eh = row.get("experiment_hash") or meta.get("experiment_hash") or ""
    hh = row.get("history_hash") or meta.get("history_hash") or ""
    fp = row.get("code_fingerprint") or ""
    if not isinstance(eh, str) or not eh.strip():
        raise IntegrityError(
            f"missing experiment_hash seal period={row.get('period')} strategy={row.get('strategy_id')}",
            hint="R-02/IC-05: freeze rows must seal experiment_hash (cannot be empty)",
        )
    if not isinstance(hh, str) or not hh.strip():
        raise IntegrityError(
            f"missing history_hash seal period={row.get('period')} strategy={row.get('strategy_id')}",
            hint="R-02/IC-03: freeze rows must seal history_hash (cannot be empty)",
        )
    if not isinstance(fp, str) or not fp.strip():
        raise IntegrityError(
            f"missing code_fingerprint seal period={row.get('period')} strategy={row.get('strategy_id')}",
            hint="R-02/IC-08: freeze rows must seal code_fingerprint (cannot be empty)",
        )
    if "outcome_hash" in row:
        oh = row.get("outcome_hash")
    elif "outcome_hash" in meta:
        oh = meta.get("outcome_hash")
    else:
        oh = None
    if oh is not None and (not isinstance(oh, str) or not oh.strip()):
        raise IntegrityError(
            f"invalid empty outcome_hash period={row.get('period')}",
            hint="use null for pre-outcome freeze, never empty string",
        )
    return eh, hh, fp, oh


def verify_freeze_row(row: dict[str, Any]) -> None:
    """Recompute freeze content_hash (IC-02) and require hard seals (R-02)."""
    if row.get("type") != "freeze":
        return
    eh, hh, fp, oh = require_freeze_seals(row)
    expected = freeze_content_hash(
        experiment_id=row["experiment_id"],
        period=row["period"],
        strategy_id=row["strategy_id"],
        tickets=row["tickets"],
        experiment_hash_=eh,
        history_hash_=hh,
        code_fingerprint_=fp,
        outcome_hash=oh,
    )
    if row.get("content_hash") != expected:
        raise IntegrityError(
            f"freeze content_hash mismatch period={row.get('period')} strategy={row.get('strategy_id')}",
            hint="tickets or seals were altered after freeze",
        )


def verify_study_semantic(root: Path) -> tuple[bool, list[str]]:
    """Full semantic audit (IC-01..05). Chain-only OK is insufficient."""
    from nullbench.core.pipeline import load_draws
    from nullbench.core.settle_math import portfolio_cost, portfolio_payout
    from nullbench.core.study import Study

    issues: list[str] = []
    study = Study(root)
    if not study.exists():
        return False, ["no study"]
    try:
        spec = study.load_experiment()
    except Exception as e:
        return False, [f"experiment load failed: {e}"]
    exp_h = experiment_hash(spec)
    draws = load_draws(study.draws_path)
    by_period = {d.period: d for d in draws}
    ledger = study.ledger()
    ok_chain, chain_msg = ledger.verify_chain()
    if not ok_chain:
        issues.append(f"chain: {chain_msg}")

    freezes = [e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id]
    for fr in freezes:
        try:
            verify_freeze_row(fr)
            eh, hh, _fp, oh = require_freeze_seals(fr)
        except IntegrityError as e:
            issues.append(str(e.message if hasattr(e, "message") else e))
            continue
        if eh != exp_h:
            issues.append(
                f"experiment_hash drift after freeze period={fr.get('period')} "
                f"(IC-05: experiment.json changed)"
            )
        hist = history_before(draws, fr["period"])
        if hh != history_hash(hist):
            issues.append(
                f"history_hash drift period={fr.get('period')} "
                f"(IC-03/04: draws reordered or history rewritten)"
            )
        if oh is not None and fr["period"] in by_period:
            if oh != outcome_hash(by_period[fr["period"]]):
                issues.append(
                    f"outcome_hash drift period={fr.get('period')} "
                    f"(IC-03: draw altered after sealed freeze)"
                )

    settles = [e for e in ledger.events_of("settle") if e.get("experiment_id") == spec.experiment_id]
    for se in settles:
        period = se["period"]
        # Prefer sealed draw on settle row
        if se.get("draw"):
            try:
                draw = Draw.model_validate(se["draw"])
            except Exception:
                issues.append(f"settle draw invalid period={period}")
                continue
        elif period in by_period:
            draw = by_period[period]
        else:
            issues.append(f"settle missing draw period={period}")
            continue
        # Recompute strategy payouts from freezes (IC-01/02)
        period_freezes = [f for f in freezes if f["period"] == period]
        for fr in period_freezes:
            tickets = [Ticket.model_validate(t) for t in fr["tickets"]]
            payout, _ = portfolio_payout(spec.game, tickets, draw)
            cost = portfolio_cost(spec.game, len(tickets))
            stored = None
            for r in se.get("strategy_results", []):
                if r.get("portfolio_id") == fr["strategy_id"]:
                    stored = r
                    break
            if stored is None:
                issues.append(f"settle missing strategy {fr['strategy_id']} period={period}")
                continue
            if abs(float(stored.get("payout", 0)) - payout) > 1e-9:
                issues.append(
                    f"forged/stale payout period={period} strategy={fr['strategy_id']}: "
                    f"ledger={stored.get('payout')} recomputed={payout} (IC-01)"
                )
            if abs(float(stored.get("cost", 0)) - cost) > 1e-9:
                issues.append(
                    f"cost mismatch period={period} strategy={fr['strategy_id']}"
                )

    return (len(issues) == 0 and ok_chain), issues


def _truthy_env(name: str) -> bool:
    import os

    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def plugin_allowlist_paths(study_root: Path | None = None) -> list[Path]:
    """Ordered allowlist locations (first existing wins when merging all)."""
    import os

    paths: list[Path] = []
    env = os.environ.get("NULLBENCH_PLUGIN_ALLOWLIST", "").strip()
    if env:
        paths.append(Path(env))
    if study_root is not None:
        paths.append(Path(study_root) / "plugins.allowlist")
    # XDG-ish / Windows user config
    home = Path.home()
    paths.append(home / ".config" / "nullbench" / "plugins.allowlist")
    return paths


def load_plugin_allowlist(study_root: Path | None = None) -> set[str]:
    """Load plugin ids from allowlist files (M3).

    Lines may be ``strategy:id``, ``domain:id``, or bare ``id``.
    Comments (``#``) and blanks ignored.
    """
    found: set[str] = set()
    for path in plugin_allowlist_paths(study_root):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" in line:
                _group, _, name = line.partition(":")
                name = name.strip()
            else:
                name = line
            if name:
                found.add(name)
                found.add(line)  # also keep prefixed form
    return found


def assert_plugins_trusted(
    kind: str,
    *,
    is_domain: bool = False,
    study_root: Path | None = None,
) -> None:
    """Gate entry-point plugins (IC-09 / M3 allowlist). Builtins always allowed."""
    from nullbench.domains import _BUILTIN as DOMAIN_BUILTIN
    from nullbench.strategies import _BUILTIN as STRAT_BUILTIN

    if is_domain:
        if kind in DOMAIN_BUILTIN:
            return
    else:
        if kind in STRAT_BUILTIN:
            return
    if _truthy_env("NULLBENCH_TRUST_PLUGINS"):
        return
    allow = load_plugin_allowlist(study_root)
    prefixed = f"{'domain' if is_domain else 'strategy'}:{kind}"
    if kind in allow or prefixed in allow:
        return
    raise IntegrityError(
        f"refusing untrusted {'domain' if is_domain else 'strategy'} plugin {kind!r}",
        hint=(
            "add the id to plugins.allowlist / NULLBENCH_PLUGIN_ALLOWLIST, "
            "or set NULLBENCH_TRUST_PLUGINS=1 (IC-09/M3)"
        ),
    )
