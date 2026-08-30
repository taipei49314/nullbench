"""Semantic integrity — hash seals beyond append-only chain.

Hash chains alone cannot stop a full-file rewrite with re-linked hashes
(IC-01). Seals bind freezes to experiment, history, code, and (when known)
outcomes; settle recomputes payouts; report prefers sealed settle draws.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from nullbench.core.hashing import content_hash, sha256_hex
from nullbench.core.models import (
    Draw,
    ExperimentSpec,
    FreezeRecord,
    HistoryAnchor,
    HistoryBoundary,
    RegistrationMode,
    SettlementMode,
    Ticket,
)
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
    """Legacy v2 history seal (intentionally excludes ``Draw.meta``)."""
    payload = [draw_payload(d) for d in order_draws(history)]
    return content_hash({"history": payload})


def history_hash_v3(history: list[Draw]) -> str:
    """Freeze-v3 history seal over complete Draw contracts, including metadata."""
    payload = [d.model_dump(mode="json") for d in order_draws(history)]
    return content_hash({"history": payload})


def make_history_anchor(history: list[Draw]) -> HistoryAnchor:
    """Commit to the exact ordered prefix available when a v3 freeze is written."""
    ordered = order_draws(history)
    through = None
    if ordered:
        last = ordered[-1]
        through = HistoryBoundary(date=last.date, period=last.period)
    return HistoryAnchor(count=len(ordered), through=through)


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
    """Legacy freeze-v2 payload. Never add fields to this function."""
    tix = [t.model_dump() if isinstance(t, Ticket) else t for t in tickets]
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


def _json_datetime(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def freeze_content_payload_v3(
    *,
    experiment_id: str,
    period: str,
    strategy_id: str,
    tickets: list[Ticket] | list[dict],
    experiment_hash_: str,
    history_hash_: str,
    code_fingerprint_: str,
    registration_mode: RegistrationMode | str,
    history_anchor: HistoryAnchor | dict[str, Any],
    outcome_hash: str | None,
    frozen_at: datetime | str,
) -> dict[str, Any]:
    """Freeze-v3 payload binding the evidence that determines registration class."""
    tix = [t.model_dump() if isinstance(t, Ticket) else t for t in tickets]
    mode = (
        registration_mode.value
        if isinstance(registration_mode, RegistrationMode)
        else str(registration_mode)
    )
    anchor = (
        history_anchor.model_dump(mode="json")
        if isinstance(history_anchor, HistoryAnchor)
        else history_anchor
    )
    return {
        "schema_version": "3",
        "experiment_id": experiment_id,
        "period": period,
        "strategy_id": strategy_id,
        "tickets": tix,
        "experiment_hash": experiment_hash_,
        "history_hash": history_hash_,
        "code_fingerprint": code_fingerprint_,
        "registration_mode": mode,
        "history_anchor": anchor,
        "outcome_hash": outcome_hash,
        "frozen_at": _json_datetime(frozen_at),
    }


def freeze_content_hash(*, schema_version: str = "2", **kwargs: Any) -> str:
    """Hash a freeze using its exact schema; default remains legacy v2 for callers."""
    schema = str(schema_version)
    if schema == "2":
        return content_hash(freeze_content_payload(**kwargs))
    if schema == "3":
        return content_hash(freeze_content_payload_v3(**kwargs))
    raise ValueError(f"unsupported freeze schema_version {schema!r}")


def outcome_hash(draw: Draw) -> str:
    return content_hash({"outcome": draw_payload(draw)})


def settle_content_hash(
    *,
    schema_version: str,
    experiment_id: str,
    period: str,
    draw: Draw | dict[str, Any],
    strategy_results: list[dict[str, Any]],
    null_pnl: list[float],
    experiment_hash_: str,
    outcome_hash_: str,
    registration_mode: SettlementMode | str | None = None,
    freeze_content_hashes: list[str] | None = None,
) -> str:
    """Hash settlement semantics with exact v1/v2 schema dispatch."""
    draw_row = draw.model_dump(mode="json") if isinstance(draw, Draw) else draw
    payload: dict[str, Any] = {
        "experiment_id": experiment_id,
        "period": period,
        "draw": draw_row,
        "strategy_results": strategy_results,
        "null_pnl": null_pnl,
        "experiment_hash": experiment_hash_,
        "outcome_hash": outcome_hash_,
    }
    schema = str(schema_version)
    if schema == "2":
        if registration_mode is None:
            raise ValueError("settle-v2 requires registration_mode")
        mode = (
            registration_mode.value
            if isinstance(registration_mode, SettlementMode)
            else str(registration_mode)
        )
        payload = {
            "schema_version": "2",
            **payload,
            "registration_mode": mode,
            "freeze_content_hashes": sorted(freeze_content_hashes or []),
        }
    elif schema != "1":
        raise ValueError(f"unsupported settle schema_version {schema!r}")
    return content_hash(payload)


def registration_class_for_freeze(row: dict[str, Any]) -> SettlementMode:
    """Classify evidence without upgrading or trusting labels on legacy freezes."""
    schema = str(row.get("schema_version", ""))
    if schema == "3":
        raw = row.get("registration_mode")
        try:
            mode = RegistrationMode(raw)
        except ValueError as e:
            raise IntegrityError(
                f"invalid registration_mode period={row.get('period')}: {raw!r}",
                hint="freeze-v3 mode must be pre_outcome or backtest",
            ) from e
        return SettlementMode(mode.value)
    if schema == "2":
        _eh, _hh, _fp, oh = require_freeze_seals(row)
        return SettlementMode.LEGACY_BACKTEST if oh is not None else SettlementMode.LEGACY_UNKNOWN
    raise IntegrityError(
        f"unsupported freeze schema_version {schema or '(missing)'}",
        hint="only freeze schema v2 and v3 are verifiable",
    )


def verify_freeze_history(draws: list[Draw], row: dict[str, Any]) -> None:
    """Verify the legacy target-relative or v3 ordered-prefix history commitment."""
    _eh, sealed_history, _fp, _oh = require_freeze_seals(row)
    schema = str(row.get("schema_version", ""))
    if schema == "2":
        expected = history_hash(history_before(draws, row["period"]))
        if sealed_history != expected:
            raise IntegrityError(
                f"history_hash drift period={row.get('period')} "
                "(IC-03/04: draws reordered or history rewritten)"
            )
        return
    if schema != "3":
        raise IntegrityError(f"unsupported freeze schema_version {schema or '(missing)'}")

    try:
        anchor = HistoryAnchor.model_validate(row.get("history_anchor"))
    except Exception as e:
        raise IntegrityError(
            f"invalid history_anchor period={row.get('period')}",
            hint="freeze-v3 requires an ordered_prefix_v1 anchor",
        ) from e
    ordered = order_draws(draws)
    if len(ordered) < anchor.count:
        raise IntegrityError(
            f"history prefix truncated period={row.get('period')}: "
            f"need {anchor.count}, found {len(ordered)}"
        )
    prefix = ordered[: anchor.count]
    if anchor.through is not None:
        last = prefix[-1]
        if (last.date, last.period) != (anchor.through.date, anchor.through.period):
            raise IntegrityError(
                f"history anchor drift period={row.get('period')} "
                "(IC-12: ordered prefix boundary changed)"
            )
    if sealed_history != history_hash_v3(prefix):
        raise IntegrityError(
            f"history_hash drift period={row.get('period')} (IC-12: ordered prefix content changed)"
        )

    mode = registration_class_for_freeze(row)
    targets = [d for d in ordered if d.period == row["period"]]
    if mode == SettlementMode.BACKTEST:
        if not targets:
            raise IntegrityError(f"backtest target missing period={row.get('period')}")
        target_history = history_before(ordered, row["period"])
        if len(target_history) != anchor.count or history_hash_v3(target_history) != sealed_history:
            raise IntegrityError(
                f"backtest history boundary drift period={row.get('period')} "
                "(IC-12: draws inserted before target)"
            )
    elif targets and prefix:
        target = targets[0]
        if draw_order_key(target) <= draw_order_key(prefix[-1]):
            raise IntegrityError(
                f"pre_outcome target is not after frozen history period={row.get('period')}",
                hint="target order key must be strictly later than the frozen prefix",
            )


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
            file_path = getattr(mod, "__file__", None)
            if file_path:
                p = Path(file_path)
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
    schema = str(row.get("schema_version", ""))
    if schema == "3":
        try:
            FreezeRecord.model_validate(row)
        except Exception as e:
            raise IntegrityError(
                f"invalid freeze-v3 evidence period={row.get('period')} "
                f"strategy={row.get('strategy_id')}",
                hint=str(e),
            ) from e
        expected = freeze_content_hash(
            schema_version="3",
            experiment_id=row["experiment_id"],
            period=row["period"],
            strategy_id=row["strategy_id"],
            tickets=row["tickets"],
            experiment_hash_=eh,
            history_hash_=hh,
            code_fingerprint_=fp,
            registration_mode=row.get("registration_mode"),
            history_anchor=row.get("history_anchor"),
            outcome_hash=oh,
            frozen_at=row.get("frozen_at"),
        )
    elif schema == "2":
        expected = freeze_content_hash(
            schema_version="2",
            experiment_id=row["experiment_id"],
            period=row["period"],
            strategy_id=row["strategy_id"],
            tickets=row["tickets"],
            experiment_hash_=eh,
            history_hash_=hh,
            code_fingerprint_=fp,
            outcome_hash=oh,
        )
    else:
        raise IntegrityError(
            f"unsupported freeze schema_version {schema or '(missing)'}",
            hint="only freeze schema v2 and v3 are verifiable",
        )
    if row.get("content_hash") != expected:
        raise IntegrityError(
            f"freeze content_hash mismatch period={row.get('period')} strategy={row.get('strategy_id')}",
            hint="tickets or seals were altered after freeze",
        )


def verify_study_semantic(root: Path) -> tuple[bool, list[str]]:
    """Full semantic audit (IC-01..05 + R-03). Chain-only OK is insufficient."""
    from nullbench.core.nullbank import evaluate_null_bank
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

    freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    freeze_keys = [(e.get("period"), e.get("strategy_id")) for e in freezes]
    duplicate_freeze_keys = sorted(
        (key for key, count in Counter(freeze_keys).items() if count > 1), key=str
    )
    if duplicate_freeze_keys:
        issues.append(f"duplicate freeze arm(s) in ledger: {duplicate_freeze_keys} (IC-13)")
    freeze_classes: set[SettlementMode] = set()
    by_freeze_period: dict[str, list[dict[str, Any]]] = {}
    for fr in freezes:
        by_freeze_period.setdefault(fr.get("period", ""), []).append(fr)
    for fr in freezes:
        try:
            verify_freeze_row(fr)
            eh, _hh, _fp, oh = require_freeze_seals(fr)
            freeze_classes.add(registration_class_for_freeze(fr))
        except IntegrityError as e:
            issues.append(str(e.message if hasattr(e, "message") else e))
            continue
        if eh != exp_h:
            issues.append(
                f"experiment_hash drift after freeze period={fr.get('period')} "
                f"(IC-05: experiment.json changed)"
            )
        try:
            verify_freeze_history(draws, fr)
        except IntegrityError as e:
            issues.append(str(e.message if hasattr(e, "message") else e))
        if (
            oh is not None
            and fr["period"] in by_period
            and oh != outcome_hash(by_period[fr["period"]])
        ):
            issues.append(
                f"outcome_hash drift period={fr.get('period')} "
                f"(IC-03: draw altered after sealed freeze)"
            )

    if len(freeze_classes) > 1:
        issues.append(
            "mixed registration modes in one experiment "
            f"({', '.join(sorted(m.value for m in freeze_classes))})"
        )
    for period, rows in by_freeze_period.items():
        frozen_strategy_ids = {str(r.get("strategy_id")) for r in rows}
        expected_strategy_ids = set(spec.strategy_ids())
        if frozen_strategy_ids != expected_strategy_ids:
            issues.append(
                f"freeze arms incomplete period={period}: "
                f"expected={sorted(expected_strategy_ids)} got={sorted(frozen_strategy_ids)} "
                "(IC-13)"
            )
        v3_rows = [r for r in rows if str(r.get("schema_version", "")) == "3"]
        if len(v3_rows) > 1:
            evidence = {
                content_hash(
                    {
                        "registration_mode": r.get("registration_mode"),
                        "history_anchor": r.get("history_anchor"),
                        "history_hash": r.get("history_hash"),
                        "outcome_hash": r.get("outcome_hash"),
                        "frozen_at": r.get("frozen_at"),
                    }
                )
                for r in v3_rows
            }
            if len(evidence) > 1:
                issues.append(f"cross-arm registration evidence mismatch period={period} (IC-13)")

    settles = [
        e for e in ledger.events_of("settle") if e.get("experiment_id") == spec.experiment_id
    ]
    settle_periods = [e.get("period") for e in settles]
    duplicate_settle_periods = sorted(
        (period for period, count in Counter(settle_periods).items() if count > 1), key=str
    )
    if duplicate_settle_periods:
        issues.append(
            f"duplicate settle period(s) in ledger: {duplicate_settle_periods} "
            "(IC-13: one observation cannot advance a formal endpoint twice)"
        )
    for se in settles:
        period = se["period"]
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
        if period not in by_period:
            issues.append(f"settle period={period} missing from draws.jsonl")
            continue
        file_draw = by_period[period]
        if draw_payload(draw) != draw_payload(file_draw):
            issues.append(
                f"settle.draw diverges from draws.jsonl period={period} "
                f"(IC-03/R-03: forged settle outcome)"
            )
            draw = file_draw
        sealed_oh = se.get("outcome_hash")
        if sealed_oh is not None and sealed_oh != outcome_hash(file_draw):
            issues.append(
                f"settle outcome_hash drift period={period} (IC-03: draw file vs settle seal)"
            )

        period_freezes = [f for f in freezes if f["period"] == period]
        expected_result_ids = [str(f.get("strategy_id")) for f in period_freezes]
        stored_result_ids = [
            str(result.get("portfolio_id")) for result in se.get("strategy_results", [])
        ]
        if Counter(stored_result_ids) != Counter(expected_result_ids):
            issues.append(
                f"settle strategy result ids mismatch period={period}: "
                f"expected={sorted(expected_result_ids)} got={sorted(stored_result_ids)}"
            )
        period_modes: set[SettlementMode] = set()
        for fr in period_freezes:
            with contextlib.suppress(IntegrityError):
                period_modes.add(registration_class_for_freeze(fr))
        if len(period_modes) != 1:
            issues.append(f"settle registration mode is ambiguous period={period}")
        else:
            derived_mode = next(iter(period_modes))
            settle_schema = str(se.get("schema_version", ""))
            if settle_schema == "2":
                if se.get("registration_mode") != derived_mode.value:
                    issues.append(f"settle registration_mode mismatch period={period} (IC-13)")
                expected_freeze_hashes = sorted(
                    str(f.get("content_hash", "")) for f in period_freezes
                )
                if se.get("freeze_content_hashes") != expected_freeze_hashes:
                    issues.append(f"settle freeze_content_hashes mismatch period={period} (IC-13)")
            elif settle_schema == "1" and any(
                str(freeze.get("schema_version", "")) == "3" for freeze in period_freezes
            ):
                issues.append(
                    f"settle schema downgrade period={period}: freeze-v3 requires settle-v2 (IC-13)"
                )
            elif settle_schema != "1":
                issues.append(
                    f"unsupported settle schema_version={settle_schema or '(missing)'} "
                    f"period={period}"
                )
        n_tickets = 0
        for fr in period_freezes:
            tickets = [Ticket.model_validate(t) for t in fr["tickets"]]
            n_tickets = max(n_tickets, len(tickets))
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
                issues.append(f"cost mismatch period={period} strategy={fr['strategy_id']}")

        if n_tickets == 0:
            n_tickets = 5
        expected_nulls = evaluate_null_bank(
            spec.game,
            draw,
            n_tickets=n_tickets,
            n_portfolios=spec.null_portfolios,
            base_seed=spec.null_seed,
        )
        stored_nulls = se.get("null_results") or []
        if len(stored_nulls) != len(expected_nulls):
            issues.append(
                f"null_results count mismatch period={period}: "
                f"ledger={len(stored_nulls)} recomputed={len(expected_nulls)} (R-03)"
            )
        else:
            by_id = {r.get("portfolio_id"): r for r in stored_nulls}
            for exp in expected_nulls:
                got = by_id.get(exp.portfolio_id)
                if got is None:
                    issues.append(f"null_results missing {exp.portfolio_id} period={period} (R-03)")
                    continue
                if abs(float(got.get("payout", 0)) - exp.payout) > 1e-9:
                    issues.append(
                        f"forged null payout period={period} {exp.portfolio_id} (R-03/IC-01)"
                    )
                if abs(float(got.get("cost", 0)) - exp.cost) > 1e-9:
                    issues.append(f"forged null cost period={period} {exp.portfolio_id} (R-03)")

        settle_schema = str(se.get("schema_version", ""))
        if settle_schema in ("1", "2"):
            try:
                expected_settle_hash = settle_content_hash(
                    schema_version=settle_schema,
                    experiment_id=se["experiment_id"],
                    period=period,
                    draw=se.get("draw") or draw.model_dump(mode="json"),
                    strategy_results=se.get("strategy_results") or [],
                    null_pnl=[
                        float(r.get("payout", 0)) - float(r.get("cost", 0))
                        for r in se.get("null_results") or []
                    ],
                    experiment_hash_=se.get("experiment_hash", ""),
                    outcome_hash_=se.get("outcome_hash", ""),
                    registration_mode=se.get("registration_mode"),
                    freeze_content_hashes=se.get("freeze_content_hashes"),
                )
                if se.get("content_hash") != expected_settle_hash:
                    issues.append(f"settle content_hash mismatch period={period} (IC-13)")
            except (TypeError, ValueError, KeyError) as e:
                issues.append(f"settle content_hash invalid period={period}: {e}")

    return (len(issues) == 0 and ok_chain), issues


def _truthy_env(name: str) -> bool:
    import os

    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def plugin_allowlist_paths(study_root: Path | None = None) -> list[Path]:
    """Allowlist locations. Study-local file is NOT trusted (A2 writable)."""
    import os

    paths: list[Path] = []
    env = os.environ.get("NULLBENCH_PLUGIN_ALLOWLIST", "").strip()
    if env:
        paths.append(Path(env))
    # Intentionally omit <study>/plugins.allowlist — A2 can write it.
    home = Path.home()
    paths.append(home / ".config" / "nullbench" / "plugins.allowlist")
    return paths


def load_plugin_allowlist(study_root: Path | None = None) -> set[str]:
    """Load plugin ids from allowlist files (M3).

    Lines may be ``strategy:id``, ``domain:id``, or bare ``id``.
    Comments (``#``) and blanks ignored.
    """
    del study_root  # kept for API compat; study path is not a trust root
    found: set[str] = set()
    for path in plugin_allowlist_paths():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" in line:
                group, _, name = line.partition(":")
                group = group.strip()
                name = name.strip()
                if group not in {"strategy", "domain"} or not name:
                    continue
                found.add(f"{group}:{name}")
            else:
                name = line
            if ":" not in line and name:
                found.add(name)
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

    del study_root  # study-local allowlist is not a trust root
    if is_domain:
        if kind in DOMAIN_BUILTIN:
            return
    else:
        if kind in STRAT_BUILTIN:
            return
    if _truthy_env("NULLBENCH_TRUST_PLUGINS"):
        return
    allow = load_plugin_allowlist()
    prefixed = f"{'domain' if is_domain else 'strategy'}:{kind}"
    if kind in allow or prefixed in allow:
        return
    raise IntegrityError(
        f"refusing untrusted {'domain' if is_domain else 'strategy'} plugin {kind!r}",
        hint=(
            "add the id to ~/.config/nullbench/plugins.allowlist or "
            "NULLBENCH_PLUGIN_ALLOWLIST, or set NULLBENCH_TRUST_PLUGINS=1 (IC-09/M3)"
        ),
    )
