"""Single source of truth for ORB-based regime classification.

Both the orchestrator (for the structural filter) and the technical agent (for
which setup criteria to apply) import this, so the two can never disagree about
what regime the market is in.

    trend_up : close broke above the opening range  -> momentum continuation
    reversal : close broke below the opening range   -> potential exhaustion/fade
    neutral  : inside the range, or no ORB available  -> stand mostly aside
"""
from __future__ import annotations


def classify_regime(fs: dict) -> str:
    close = fs.get("last_close")
    orb_high = fs.get("orb_high")
    orb_low = fs.get("orb_low")
    if close is None or orb_high is None or orb_low is None:
        return "neutral"
    if close > orb_high:
        return "trend_up"
    if close < orb_low:
        return "reversal"
    return "neutral"
