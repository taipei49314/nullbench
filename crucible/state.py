"""不可變狀態表示。

狀態是「變數名 -> 值」的不可變映射。鍵必須是 `str`,值必須可雜湊 ——
這兩項限制讓狀態天生可雜湊、可比較,而且 `repr` 是決定性的(鍵依序排列)。

決定性是本專案的地基:任何依賴 dict/set 迭代順序的做法都會讓反例軌跡在不同執行間漂移。
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Mapping


class StateError(TypeError):
    """狀態建構時的型別違規。"""


class State:
    """不可變、可雜湊的變數映射。

    >>> s = State({"n": 0})
    >>> s.set("n", 1)["n"]
    1
    >>> s["n"]
    0
    """

    __slots__ = ("_items", "_hash")

    def __init__(self, mapping: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        data: dict[str, Any] = {}
        if mapping is not None:
            data.update(mapping)
        data.update(kwargs)

        for key, value in data.items():
            if not isinstance(key, str):
                raise StateError(f"state keys must be str, got {type(key).__name__}: {key!r}")
            try:
                hash(value)
            except TypeError as exc:
                raise StateError(
                    f"state value for {key!r} must be hashable, got {type(value).__name__}"
                ) from exc

        # 依鍵排序後凍結 —— repr、雜湊、迭代順序全部因此變成決定性的。
        self._items: tuple[tuple[str, Any], ...] = tuple(sorted(data.items()))
        self._hash: int = hash(self._items)

    # -- 讀取 ---------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        for k, v in self._items:
            if k == key:
                return v
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self._items:
            if k == key:
                return v
        return default

    def __contains__(self, key: object) -> bool:
        return any(k == key for k, _ in self._items)

    def keys(self) -> tuple[str, ...]:
        return tuple(k for k, _ in self._items)

    def values(self) -> tuple[Any, ...]:
        return tuple(v for _, v in self._items)

    def items(self) -> tuple[tuple[str, Any], ...]:
        return self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self._items)

    # -- 衍生 ---------------------------------------------------------------

    def set(self, key: str, value: Any) -> "State":
        """回傳套用單一鍵之後的新狀態。原狀態不變。"""
        return State(dict(self._items) | {key: value})

    def update(self, mapping: Mapping[str, Any] | None = None, **kwargs: Any) -> "State":
        """回傳套用多個鍵之後的新狀態。原狀態不變。"""
        merged = dict(self._items)
        if mapping is not None:
            merged.update(mapping)
        merged.update(kwargs)
        return State(merged)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._items)

    # -- 身分 ---------------------------------------------------------------

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, State):
            return NotImplemented
        return self._items == other._items

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self._items)
        return f"State({inner})"


def states_key(states: Iterable[State]) -> tuple[str, ...]:
    """把一組狀態轉成決定性的排序鍵 —— 用於需要穩定輸出順序的場合。"""
    return tuple(sorted(repr(s) for s in states))
