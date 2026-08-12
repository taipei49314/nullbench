"""User-facing error hierarchy — CLI maps these to clean messages."""

from __future__ import annotations


class NullbenchError(Exception):
    """Base error with optional hint for the next action."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def format(self) -> str:
        if self.hint:
            return f"{self.message}\n  hint: {self.hint}"
        return self.message


class StudyNotFoundError(NullbenchError):
    pass


class StudyExistsError(NullbenchError):
    pass


class DomainError(NullbenchError):
    pass


class StrategyError(NullbenchError):
    pass


class FreezeError(NullbenchError):
    pass


class SettleError(NullbenchError):
    pass


class DataError(NullbenchError):
    pass


class IntegrityError(NullbenchError):
    pass


class VaultError(NullbenchError):
    """M4 vault / notary / sealed-bundle errors."""

    pass
