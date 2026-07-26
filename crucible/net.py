"""確定性的多重集合訊息袋。

訊息袋是不可變、可雜湊的 State 值。相同訊息的多次送出會保留計數，
而袋子的值與 ``send`` 的呼叫順序無關。
"""

from __future__ import annotations

from typing import Any

from .state import State


def _sort_key(message: Any) -> tuple[str, str, str]:
    """為常見及自訂 hashable 訊息提供穩定的顯示排序鍵。"""

    message_type = type(message)
    return (
        f"{message_type.__module__}.{message_type.__qualname__}",
        repr(message),
        str(message_type),
    )


class MessageBag:
    """不可變訊息多重集合；不要依賴其內部表示，使用本模組函式操作。"""

    __slots__ = ("_entries", "_hash")

    def __init__(self, entries: tuple[tuple[Any, int], ...] = ()) -> None:
        normalized: list[tuple[Any, int]] = []
        for message, count in entries:
            if count < 1:
                raise ValueError("message count must be positive")
            try:
                hash(message)
            except TypeError as exc:
                raise TypeError("messages must be hashable") from exc

            for index, (existing, existing_count) in enumerate(normalized):
                if existing == message:
                    normalized[index] = (existing, existing_count + count)
                    break
            else:
                normalized.append((message, count))

        self._entries = tuple(sorted(normalized, key=lambda item: _sort_key(item[0])))
        self._hash = hash(self._entries)

    def add(self, message: Any) -> "MessageBag":
        return MessageBag(self._entries + ((message, 1),))

    def remove(self, message: Any) -> "MessageBag":
        for index, (existing, count) in enumerate(self._entries):
            if existing == message:
                remaining = self._entries[:index] + self._entries[index + 1 :]
                if count > 1:
                    remaining += ((existing, count - 1),)
                return MessageBag(remaining)
        raise ValueError(f"message is not pending: {message!r}")

    def pending(self) -> tuple[Any, ...]:
        return tuple(message for message, count in self._entries for _ in range(count))

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MessageBag):
            return NotImplemented
        return self._entries == other._entries

    def __repr__(self) -> str:
        return f"MessageBag({self.pending()!r})"


def empty() -> MessageBag:
    """回傳空訊息袋。"""

    return MessageBag()


def _bag_from_state(state: State, channel: str) -> MessageBag:
    value = state.get(channel)
    if value is None:
        return empty()
    if not isinstance(value, MessageBag):
        raise TypeError(f"state channel {channel!r} does not contain a MessageBag")
    return value


def send(state: State, channel: str, message: Any) -> State:
    """在 channel 尾端送入一份 message，回傳新 State。"""

    return state.set(channel, _bag_from_state(state, channel).add(message))


def pending(state: State, channel: str) -> tuple[Any, ...]:
    """以決定性順序回傳 channel 中所有待處理訊息（含重複項）。"""

    return _bag_from_state(state, channel).pending()


def deliver(state: State, channel: str, message: Any) -> State:
    """移除 channel 中一份 message；不存在時拒絕操作。"""

    bag = _bag_from_state(state, channel)
    return state.set(channel, bag.remove(message))


__all__ = ["MessageBag", "empty", "send", "pending", "deliver"]
