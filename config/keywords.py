"""Hot-reloadable keyword lists for the X sentiment feature engine.

Call `reload_keywords()` at any time to pick up edits to
config/keywords_override.json without restarting the process.  If the override
file is absent the module-level defaults are used.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import FrozenSet

logger = logging.getLogger(__name__)

_OVERRIDE_PATH = Path(__file__).parent / "keywords_override.json"

# --------------------------------------------------------------------------- #
# Defaults — edit keywords_override.json to change at runtime
# --------------------------------------------------------------------------- #
_DEFAULTS: dict[str, list[str]] = {
    "risk_keywords": [
        "EMERGENCY", "CRASH", "CRISIS", "COLLAPSE", "HALT", "FREEZE",
        "SYSTEMIC", "CONTAGION", "BAILOUT", "DEFAULT", "RECESSION",
        "WAR", "ESCALATION", "SANCTIONS", "TARIFF", "INFLATION",
        "RATE HIKE", "FED", "FOMC", "BLACK SWAN", "CIRCUIT BREAKER",
        "BANK RUN", "LIQUIDITY", "INSOLVENCY", "DOWNGRADE", "LAYOFFS",
    ],
    "bullish_flow_keywords": [
        "BULLISH", "CALLS", "SWEEP", "UNUSUAL CALLS", "BUY",
        "LONG", "UPSIDE", "BREAKOUT", "RECORD HIGH", "RALLY",
        "UPGRADE", "BEAT", "STRONG EARNINGS", "BIG CALLS",
        "GOLDEN CROSS", "SQUEEZE",
    ],
    "bearish_flow_keywords": [
        "BEARISH", "PUTS", "UNUSUAL PUTS", "SELL", "SHORT",
        "DOWNSIDE", "BREAKDOWN", "RECORD LOW", "SELLOFF",
        "DOWNGRADE", "MISS", "WEAK EARNINGS", "BIG PUTS",
        "DEATH CROSS", "DUMP",
    ],
    "macro_shock_keywords": [
        "BREAKING", "FLASH", "ALERT", "DEVELOPING", "JUST IN",
        "URGENT", "HEADLINE", "WIRE", "SOURCE",
    ],
    "options_flow_keywords": [
        "PUT", "CALL", "OI", "OPEN INTEREST", "PREMIUM",
        "STRIKE", "EXPIRY", "IV", "IMPLIED VOL", "DELTA",
        "NET PREMIUM", "FLOW", "BLOCK", "SWEEP",
    ],
}

# Live keyword sets — module attribute so callers do `from config.keywords import RISK_KEYWORDS`
RISK_KEYWORDS: FrozenSet[str] = frozenset()
BULLISH_FLOW_KEYWORDS: FrozenSet[str] = frozenset()
BEARISH_FLOW_KEYWORDS: FrozenSet[str] = frozenset()
MACRO_SHOCK_KEYWORDS: FrozenSet[str] = frozenset()
OPTIONS_FLOW_KEYWORDS: FrozenSet[str] = frozenset()


def _load() -> dict[str, list[str]]:
    if _OVERRIDE_PATH.exists():
        try:
            with _OVERRIDE_PATH.open() as f:
                overrides = json.load(f)
            merged = {**_DEFAULTS, **overrides}
            logger.info("keywords: loaded overrides from %s", _OVERRIDE_PATH)
            return merged
        except Exception as exc:
            logger.warning("keywords: failed to load override (%s), using defaults", exc)
    return _DEFAULTS


def reload_keywords() -> None:
    """Re-read the override file and refresh all module-level keyword sets."""
    global RISK_KEYWORDS, BULLISH_FLOW_KEYWORDS, BEARISH_FLOW_KEYWORDS
    global MACRO_SHOCK_KEYWORDS, OPTIONS_FLOW_KEYWORDS

    data = _load()
    RISK_KEYWORDS = frozenset(k.upper() for k in data.get("risk_keywords", []))
    BULLISH_FLOW_KEYWORDS = frozenset(k.upper() for k in data.get("bullish_flow_keywords", []))
    BEARISH_FLOW_KEYWORDS = frozenset(k.upper() for k in data.get("bearish_flow_keywords", []))
    MACRO_SHOCK_KEYWORDS = frozenset(k.upper() for k in data.get("macro_shock_keywords", []))
    OPTIONS_FLOW_KEYWORDS = frozenset(k.upper() for k in data.get("options_flow_keywords", []))
    logger.debug(
        "keywords reloaded: risk=%d bullish=%d bearish=%d macro=%d options=%d",
        len(RISK_KEYWORDS), len(BULLISH_FLOW_KEYWORDS), len(BEARISH_FLOW_KEYWORDS),
        len(MACRO_SHOCK_KEYWORDS), len(OPTIONS_FLOW_KEYWORDS),
    )


# Load on import
reload_keywords()
