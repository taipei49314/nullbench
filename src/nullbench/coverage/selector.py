"""Max-disjoint multi-ticket coverage via OR-Tools CP-SAT (greedy fallback).

Goal: pick `n_tickets` lines of size `main_count` with **pairwise disjoint**
main numbers, preferring higher-weight numbers. This maximises union coverage
of a ranked support set under a fixed ticket budget — *not* hit probability
of any single number beyond the combinatorial structure.

Requires optional extra: `pip install nullbench[coverage]` (ortools).
"""

from __future__ import annotations

from dataclasses import dataclass

from nullbench.core.models import GameSpec, SpecialMode, Ticket


@dataclass
class CoveragePlan:
    tickets: list[Ticket]
    union_size: int
    total_weight: float
    backend: str
    numbers_used: list[int]
    note: str


def select_max_disjoint_coverage(
    game: GameSpec,
    ranked_numbers: list[int],
    *,
    n_tickets: int = 5,
    weights: dict[int, float] | None = None,
    special: int | None = None,
    time_limit_s: float = 5.0,
) -> CoveragePlan:
    """
    Select up to n_tickets disjoint main_count-subsets from ranked_numbers.

    ranked_numbers: preference order (first = best). Weights default to
    reverse-rank scores. Special ball: only for SEPARATE mode.
    """
    need = n_tickets * game.main_count
    pool = [n for n in ranked_numbers if 1 <= n <= game.main_max]
    # de-dupe preserving order
    seen: set[int] = set()
    ordered: list[int] = []
    for n in pool:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    if len(ordered) < need:
        raise ValueError(
            f"need {need} distinct numbers for {n_tickets} disjoint tickets; got {len(ordered)}"
        )

    w = weights or {n: float(len(ordered) - i) for i, n in enumerate(ordered)}

    try:
        return _ortools_select(game, ordered, n_tickets, w, special, time_limit_s)
    except Exception:
        return _greedy_select(game, ordered, n_tickets, w, special)


def _assign_special(game: GameSpec, special: int | None) -> int | None:
    if game.special_mode != SpecialMode.SEPARATE:
        return None
    if special is not None:
        return special
    if game.special_max is None:
        return None
    return 1


def _greedy_select(
    game: GameSpec,
    ordered: list[int],
    n_tickets: int,
    weights: dict[int, float],
    special: int | None,
) -> CoveragePlan:
    """Take top numbers in order, pack into tickets of main_count."""
    take = ordered[: n_tickets * game.main_count]
    tickets: list[Ticket] = []
    sp = _assign_special(game, special)
    for t in range(n_tickets):
        chunk = take[t * game.main_count : (t + 1) * game.main_count]
        tickets.append(Ticket(numbers=sorted(chunk), special=sp, label=f"cov-{t + 1}"))
    used = sorted({n for tk in tickets for n in tk.numbers})
    tw = sum(weights.get(n, 0.0) for n in used)
    return CoveragePlan(
        tickets=tickets,
        union_size=len(used),
        total_weight=tw,
        backend="greedy",
        numbers_used=used,
        note="Greedy top-rank packing; install ortools for CP-SAT optimisation.",
    )


def _ortools_select(
    game: GameSpec,
    ordered: list[int],
    n_tickets: int,
    weights: dict[int, float],
    special: int | None,
    time_limit_s: float,
) -> CoveragePlan:
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    # x[t, n] = number n used on ticket t
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for t in range(n_tickets):
        for n in ordered:
            x[t, n] = model.NewBoolVar(f"x_{t}_{n}")

    # each ticket has exactly main_count numbers
    for t in range(n_tickets):
        model.Add(sum(x[t, n] for n in ordered) == game.main_count)

    # each number on at most one ticket (disjoint)
    for n in ordered:
        model.Add(sum(x[t, n] for t in range(n_tickets)) <= 1)

    # maximise total weight of used numbers
    model.Maximize(
        sum(int(weights.get(n, 0) * 1000) * x[t, n] for t in range(n_tickets) for n in ordered)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT failed: {status}")

    sp = _assign_special(game, special)
    tickets: list[Ticket] = []
    used: list[int] = []
    for t in range(n_tickets):
        nums = [n for n in ordered if solver.Value(x[t, n]) == 1]
        tickets.append(Ticket(numbers=sorted(nums), special=sp, label=f"cov-{t + 1}"))
        used.extend(nums)
    used_sorted = sorted(set(used))
    tw = sum(weights.get(n, 0.0) for n in used_sorted)
    return CoveragePlan(
        tickets=tickets,
        union_size=len(used_sorted),
        total_weight=tw,
        backend="ortools.cp_sat",
        numbers_used=used_sorted,
        note=(
            "Disjoint multi-ticket coverage maximising rank weight. "
            "This improves union structure, not calibrated hit odds."
        ),
    )
