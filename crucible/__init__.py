"""crucible —— 確定性協定模型檢查器。

窮舉併發／分散式協定的狀態空間,找出違反不變量的最短反例軌跡。
純標準函式庫、不連網、完全決定性。

規格見 SPEC.md。
"""

from .checker import Checker, Result, Trace, Violation
from .model import Action, Invariant, Model, ModelError
from .state import State, StateError

__version__ = "0.1.0"

__all__ = [
    "Action",
    "Checker",
    "Invariant",
    "Model",
    "ModelError",
    "Result",
    "State",
    "StateError",
    "Trace",
    "Violation",
    "__version__",
]
