from __future__ import annotations

import importlib.util

import numpy as np

from nullbench.coverage import select_max_disjoint_coverage
from nullbench.domains.demo649 import GAME
from nullbench.scoring.comparecast_adapter import compare_deltas, eprocess_expm
from nullbench.scoring.sequential import e_process_from_deltas


def test_comparecast_positive_deltas_raise_e() -> None:
    deltas = [10.0] * 20
    r = compare_deltas(deltas, method="asymptotic")
    assert r.n == 20
    assert r.mean_delta > 0
    assert r.e_pq > 1.0
    # CS should sit above 0 for strong positive signal
    assert r.lcb > 0 or r.ucb > 0


def test_eprocess_symmetry() -> None:
    xs = np.array([1.0, -1.0, 0.5, -0.5, 0.2])
    e1 = eprocess_expm(xs, c=2.0)
    e2 = eprocess_expm(-xs, c=2.0)
    assert len(e1) == len(xs)
    assert e1[-1] > 0 and e2[-1] > 0


def test_sequential_uses_comparecast_compat() -> None:
    ev = e_process_from_deltas([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
    assert "comparecast" in ev.backend
    assert ev.lcb is not None
    assert ev.e_pq is not None


def test_coverage_disjoint() -> None:
    ranked = list(range(1, 49))
    plan = select_max_disjoint_coverage(GAME, ranked, n_tickets=5)
    assert plan.union_size == 30
    assert len(plan.tickets) == 5
    all_nums = [n for t in plan.tickets for n in t.numbers]
    assert len(all_nums) == len(set(all_nums))
    expected_backend = "ortools.cp_sat" if importlib.util.find_spec("ortools") else "greedy"
    assert plan.backend == expected_backend
