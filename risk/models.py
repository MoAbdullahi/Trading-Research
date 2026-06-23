"""Layer 4 — Pydantic models for the deterministic Risk Gateway.

These are the verification contracts. The gateway takes a (TradePlan,
AccountState, MarketContext) triple and returns a RiskDecision. Everything here
is pure data + validation — no LLM, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AssetClass, RejectReason, Side


class MarketContext(BaseModel):
    """Live facts the gateway needs that aren't in the plan or account."""
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_class: AssetClass
    last_price: float = Field(gt=0)
    is_shortable: bool = True
    ssr_active: bool = False          # equities short-sale restriction
    session_open: bool = True
    min_tick: float = 0.01
    contract_multiplier: float = 1.0  # 1 for stocks/crypto; per-instrument for FX/CFD
    atr: float = Field(default=0.0, ge=0.0)  # current ATR; enables the ATR-relative stop floor


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    equity: float = Field(gt=0)
    cash: float
    buying_power: float = Field(ge=0)
    open_exposure_value: float = Field(ge=0, default=0.0)
    high_water_equity: float = Field(gt=0)        # for drawdown lock
    is_pattern_day_trader: bool = False
    day_trade_count_5d: int = Field(ge=0, default=0)


class RiskLimits(BaseModel):
    """Immutable global limits. Loaded from settings; never widened at runtime."""
    model_config = ConfigDict(frozen=True)

    max_per_trade_risk_pct: float = Field(gt=0, le=2.0, default=2.0)
    min_reward_to_risk: float = Field(ge=1.0, default=2.0)
    min_stop_distance_pct: float = Field(ge=0, default=0.003)  # fallback pct floor when ATR unavailable
    min_stop_atr_mult: float = Field(ge=0, default=0.15)  # ATR-relative floor (primary); admits structural SMC stops
    max_concurrent_exposure_pct: float = Field(gt=0, le=100.0, default=30.0)
    max_account_drawdown_pct: float = Field(gt=0, le=100.0, default=6.0)
    pdt_min_equity: float = Field(default=25_000.0)
    pdt_max_day_trades: int = Field(default=3)

    # Volatility regime adjustments (applied by gateway when plan.volatility_alert=True)
    volatility_size_reduction: float = Field(ge=0.0, le=1.0, default=0.5)    # multiply max_risk_pct by this
    volatility_stop_atr_mult_scale: float = Field(ge=1.0, default=1.5)       # widen ATR stop floor by this factor
    volatility_circuit_breaker_count: int = Field(ge=1, default=3)           # consecutive alerts → freeze
    volatility_freeze_minutes: int = Field(ge=1, default=30)                 # freeze duration


@dataclass
class VolatilityCircuitBreaker:
    """Mutable singleton tracking consecutive volatility alerts.

    NOT a Pydantic model — it is intentionally mutable state that persists
    across calls within a single process lifetime.  The gateway holds one
    instance and updates it on each evaluate() call.
    """
    consecutive_alerts: int = 0
    freeze_until: Optional[datetime] = field(default=None)

    def record_alert(self, limits: RiskLimits, now: datetime) -> None:
        self.consecutive_alerts += 1
        if self.consecutive_alerts >= limits.volatility_circuit_breaker_count:
            from datetime import timedelta
            self.freeze_until = now + timedelta(minutes=limits.volatility_freeze_minutes)
            import logging
            logging.getLogger(__name__).warning(
                "CIRCUIT BREAKER TRIGGERED: %d consecutive volatility alerts → "
                "all entries frozen until %s",
                self.consecutive_alerts, self.freeze_until.isoformat(),
            )

    def record_no_alert(self) -> None:
        self.consecutive_alerts = 0

    def is_frozen(self, now: datetime) -> bool:
        if self.freeze_until is None:
            return False
        if now >= self.freeze_until:
            self.freeze_until = None   # thaw automatically
            self.consecutive_alerts = 0
            return False
        return True


class SizedOrder(BaseModel):
    """The concrete, broker-ready order the gateway produces on approval."""
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Side
    qty: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    take_profit_prices: list[float] = Field(min_length=1)
    dollar_risk: float = Field(ge=0)
    reward_to_risk: float = Field(ge=0)


class RiskCheck(BaseModel):
    name: str
    passed: bool
    reason: RejectReason = RejectReason.OK
    detail: str = ""


class RiskDecision(BaseModel):
    """The gateway's verdict. `approved` is True only if every check passed."""
    plan_id: str
    symbol: str
    approved: bool
    checks: list[RiskCheck] = Field(default_factory=list)
    sized_order: Optional[SizedOrder] = None
    decided_at: datetime

    @property
    def first_failure(self) -> Optional[RiskCheck]:
        return next((c for c in self.checks if not c.passed), None)
