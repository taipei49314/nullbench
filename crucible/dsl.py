"""宣告式模型語言。

`Spec` 把以方法寫成的 action 展開成一般的 :class:`~crucible.model.Action`。
action 的方法只需要回傳後繼狀態；空的後繼序列代表該 action 在目前狀態
沒有啟用。參數化 action 的參數來源是 Spec 上指定的可迭代屬性。
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Iterable

from .model import Action, Model
from .state import State


_ACTION_MARKER = "__crucible_action__"


def action(
    function: Callable[..., Iterable[State]] | None = None,
    *,
    params: str | None = None,
) -> Callable[..., Iterable[State]] | Callable[[Callable[..., Iterable[State]]], Callable[..., Iterable[State]]]:
    """標記一個 Spec 方法為 action。

    ``@action()`` 保留方法名；``@action(params="nodes")`` 則依照
    ``self.nodes`` 展開成一個參數一個 action。
    """

    if params is not None and not isinstance(params, str):
        raise TypeError("action params must be a string or None")

    def decorate(method: Callable[..., Iterable[State]]) -> Callable[..., Iterable[State]]:
        setattr(method, _ACTION_MARKER, params)
        return method

    if function is None:
        return decorate
    return decorate(function)


class Spec(Model):
    """以 decorated methods 宣告 actions 的 Model 基底類別。"""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # 規格允許 init() 直接回傳一個 State，但 Model 的通用入口和
        # 前線測試的獨立重播都需要可迭代的初始狀態集合。只在每個實際
        # 宣告 init 的子類別邊界做正規化，並保留 list/generator 的原意。
        declared_init = cls.__dict__.get("init")
        if declared_init is None or getattr(declared_init, "__crucible_init_normalized__", False):
            return

        @wraps(declared_init)
        def normalized_init(self: "Spec", *args: Any, **init_kwargs: Any) -> Any:
            result = declared_init(self, *args, **init_kwargs)
            if isinstance(result, State):
                return (result,)
            return result

        setattr(normalized_init, "__crucible_init_normalized__", True)
        cls.init = normalized_init  # type: ignore[assignment]

    def actions(self) -> Iterable[Action]:
        """依方法名穩定展開所有繼承而來的 decorated actions。"""

        # dir(type(self)) 本身是排序後的名稱序列，避免把 class __dict__ 的
        # 宣告順序或任何映射迭代順序洩漏到模型探索裡。
        for method_name in dir(type(self)):
            method = getattr(type(self), method_name)
            if not callable(method) or not hasattr(method, _ACTION_MARKER):
                continue

            params_name = getattr(method, _ACTION_MARKER)
            bound = getattr(self, method_name)
            if params_name is None:
                yield self._make_action(method_name, bound)
                continue

            try:
                parameters = getattr(self, params_name)
            except AttributeError as exc:
                raise AttributeError(
                    f"action {method_name!r} refers to missing params attribute {params_name!r}"
                ) from exc

            try:
                values = tuple(parameters)
            except TypeError as exc:
                raise TypeError(
                    f"action {method_name!r} params attribute {params_name!r} must be iterable"
                ) from exc

            for value in values:
                name = f"{method_name}({value})"
                yield self._make_action(name, bound, value)

    @staticmethod
    def _make_action(name: str, method: Callable[..., Iterable[State]], *parameter: Any) -> Action:
        def successors(state: State) -> tuple[State, ...]:
            return tuple(method(state, *parameter))

        # DSL methods have no separate guard. Calling the method for the guard
        # makes an empty result semantically identical to a disabled action.
        def enabled(state: State) -> bool:
            return bool(successors(state))

        return Action(name, enabled, successors)


__all__ = ["Spec", "action"]
