from __future__ import annotations

from nullbench.core.models import GameSpec, SpecialMode, StrategySpec, Ticket
from nullbench.strategies import get_strategy, list_strategies, register_strategy


def test_list_includes_builtins() -> None:
    names = list_strategies()
    assert "random" in names
    assert "frequency" in names


def test_runtime_register() -> None:
    def propose_const(game, spec, history, period_seed):
        del history, period_seed
        tickets = []
        base = list(range(1, game.main_count + 1))
        for i in range(spec.tickets_per_period):
            nums = [((x + i - 1) % game.main_max) + 1 for x in base]
            # ensure unique sorted
            nums = sorted(set(nums))
            while len(nums) < game.main_count:
                nums.append(len(nums) + 1)
            tickets.append(Ticket(numbers=sorted(nums)[: game.main_count]))
        return tickets

    register_strategy("const_test", propose_const)
    fn = get_strategy("const_test")
    game = GameSpec(
        id="g",
        name="g",
        main_count=6,
        main_max=49,
        special_mode=SpecialMode.NONE,
        ticket_cost=1.0,
    )
    spec = StrategySpec(id="c", kind="const_test", tickets_per_period=2)
    out = fn(game, spec, [], 1)
    assert len(out) == 2
