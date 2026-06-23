"""Shared enumerations used across every layer.

Keeping these centralized prevents the classic bug where the agent lane and the
execution lane disagree on the string value of a side or a state.
"""
from __future__ import annotations

from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    GOLD = "gold"  # XAUUSD — treated separately because its drivers differ from FX majors


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class Bias(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SetupType(str, Enum):
    ORB = "opening_range_breakout"
    VWAP_RECLAIM = "vwap_reclaim"
    VWAP_REJECT = "vwap_reject"
    SUPPORT_BOUNCE = "support_bounce"
    RESISTANCE_REJECT = "resistance_reject"
    RED_TO_GREEN = "red_to_green"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"


class SymbolState(str, Enum):
    """The per-symbol state machine that the LangGraph graph walks."""
    SCANNING = "scanning"
    PLAN_ARMED = "plan_armed"
    IN_TRADE = "in_trade"
    MANAGING = "managing"
    FLAT = "flat"


class AgentVote(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    ABSTAIN = "abstain"


class RejectReason(str, Enum):
    OK = "ok"
    RISK_TOO_HIGH = "per_trade_risk_exceeds_cap"
    RR_TOO_LOW = "reward_to_risk_below_minimum"
    PDT_BLOCK = "pattern_day_trader_block"
    SSR_BLOCK = "short_sale_restriction"
    NO_SHORT_SPOT = "shorting_not_supported_on_spot"
    EXPOSURE_CAP = "max_concurrent_exposure_exceeded"
    DRAWDOWN_LOCK = "max_drawdown_lock_triggered"
    MARGIN_INSUFFICIENT = "insufficient_buying_power"
    MALFORMED_PLAN = "malformed_trade_plan"
    SESSION_CLOSED = "market_session_closed"
    STOP_TOO_TIGHT = "stop_distance_below_minimum"
    VOLATILITY_FREEZE = "circuit_breaker_volatility_freeze"
