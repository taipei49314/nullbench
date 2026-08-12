"""Scoring adapters — prefer giants; keep thin local fallbacks."""

from nullbench.scoring.brier import brier_for_main_balls
from nullbench.scoring.summary import period_score_summary

__all__ = ["brier_for_main_balls", "period_score_summary"]
