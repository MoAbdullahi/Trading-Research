"""Pydantic v2 data contracts shared between the slow loop and the fast loop.

The TradePlan is the *immutable* hand-off object: the LLM lane produces it, the
deterministic Risk Gateway consumes it. Nothing else crosses the boundary.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import AgentVote, AssetClass, Bias, SetupType


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
class Bar(BaseModel):
    """A single OHLCV bar, normalized across every venue adapter."""
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_class: AssetClass
    ts: datetime  # bar close time, timezone-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True  # feature engine MUST ignore bars where this is False

    @field_validator("high")
    @classmethod
    def _high_is_highest(cls, v: float, info):
        # light sanity check; full validation happens in the ingestion adapter
        return v


class KeyLevels(BaseModel):
    """Entry / stop / targets for an armed setup. Targets are ordered nearest-first."""
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    targets: list[float] = Field(min_length=1)

    @model_validator(mode="after")
    def _stop_differs_from_entry(self):
        if self.stop == self.entry:
            raise ValueError("stop must differ from entry")
        return self

    def reward_to_risk(self, side_is_long: bool) -> float:
        """RR measured to the *first* target — the gateway re-checks this."""
        risk = abs(self.entry - self.stop)
        if risk == 0:
            return 0.0
        reward = (self.targets[0] - self.entry) if side_is_long else (self.entry - self.targets[0])
        return reward / risk


class ArmedSetup(BaseModel):
    setup_type: SetupType
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


# --------------------------------------------------------------------------- #
# Agent outputs
# --------------------------------------------------------------------------- #
class AgentSignal(BaseModel):
    """Standardized output every LLM agent must return. Keeps the consensus
    tally purely deterministic — the orchestrator never re-parses free text."""
    agent_name: str
    vote: AgentVote
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    raw_response: Optional[str] = None  # full LLM string, persisted to the audit log
    proposed_levels: Optional[KeyLevels] = None  # structural levels from provider (CRT, ICT, etc.)


# --------------------------------------------------------------------------- #
# The immutable hand-off object
# --------------------------------------------------------------------------- #
class TradePlan(BaseModel):
    """Emitted by the orchestrator, consumed by the Risk Gateway. Frozen so no
    downstream code can silently mutate a level after consensus was reached."""
    model_config = ConfigDict(frozen=True)

    plan_id: str
    symbol: str
    asset_class: AssetClass
    bias: Bias
    armed_setups: list[ArmedSetup] = Field(default_factory=list)
    key_levels: Optional[KeyLevels] = None
    max_risk_pct: float = Field(gt=0.0, le=2.0, description="hard-capped at 2% upstream")
    consensus_score: int = Field(ge=0, le=5)
    created_at: datetime
    expires_at: datetime

    volatility_alert: bool = False  # set by x_sentiment_agent; gates 50% size reduction

    @model_validator(mode="after")
    def _flat_plans_need_no_levels(self):
        if self.bias is not Bias.FLAT and self.key_levels is None:
            raise ValueError("a directional plan must include key_levels")
        return self


# --------------------------------------------------------------------------- #
# X / Social sentiment schemas  (immutable, strict — no extra fields allowed)
# --------------------------------------------------------------------------- #
class RawTweetRecord(BaseModel):
    """Single tweet record stored in the append-only Postgres raw_tweets table."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    tweet_id: str
    author_handle: str
    text: str
    timestamp: datetime
    is_all_caps: bool
    contains_market_flow: bool


class XSentimentMetrics(BaseModel):
    """Deterministic quant metrics derived from a 15-min rolling tweet window.
    Never shown to an LLM directly — used as the gate and compressed input."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    volume_spike_ratio: float          # current-window count / EWMA baseline
    model_score: float = Field(ge=-1.0, le=1.0)  # keyword-weighted sentiment score
    high_impact_text_samples: List[str]           # top-5 de-duped, cleaned samples
    impact_score: float                           # weighted composite (0-1)
    source_tweet_ids: List[str]                   # traceable back to raw_tweets


class XSentimentSignal(BaseModel):
    """Structured output produced by the x_sentiment_agent LLM call (or static
    NEUTRAL when the volume gate is not met).  Consumed by the orchestrator."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    sentiment_bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    conviction_score: float = Field(ge=0.0, le=1.0)
    volatility_alert: bool
    primary_catalyst_summary: str
    source_tweet_ids: List[str]
