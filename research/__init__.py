"""lotto-lab 的離線研究層。

這個套件只讀取官方歷史快取，不讀寫 v1 的正式帳本。研究結果放在
``research/results``，不得回填或覆蓋 ``records``。
"""

from .backtest import run_study

__all__ = ["run_study"]
