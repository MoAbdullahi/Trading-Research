"""Pytest suite for the deterministic Risk Gateway.

Covers every rule in RiskGateway.evaluate() so regressions are caught before
they reach a live run. All inputs are constructed directly — no network, no LLM.

Run:  pytest tests/test_risk_gateway.py -v
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import AssetClass, Bias, RejectReason, Side
from core.schemas import KeyLevels, TradePlan, ArmedSetup, SetupType
from risk.gateway import RiskGateway
from risk.models import AccountSnapshot, MarketContext, RiskLimits, SizedOrder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)
_LIMITS = RiskLimits(
    max_per_trade_risk_pct=2.0,
    min_reward_to_risk=2.0,
    max_concurrent_exposure_pct=30.0,
    max_account_drawdown_pct=6.0,
)
_ACCOUNT = AccountSnapshot(
    equity=100_000.0,
    cash=100_000.0,
    buying_power=200_000.0,
    open_exposure_value=0.0,
    high_water_equity=100_000.0,
    is_pattern_day_trader=False,
    day_trade_count_5d=0,
)
_MARKET = MarketContext(
    symbol="AAPL",
    asset_class=AssetClass.EQUITY,
    last_price=150.0,
    is_shortable=True,
    ssr_active=False,
    session_open=True,
)


def _long_plan(entry=150.0, stop=148.0, targets=None, max_risk_pct=2.0) -> TradePlan:
    return TradePlan(
        plan_id="test-long",
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        bias=Bias.LONG,
        armed_setups=[ArmedSetup(setup_type=SetupType.VWAP_RECLAIM, confidence=0.8)],
        key_levels=KeyLevels(
            entry=entry,
            stop=stop,
            targets=targets or [round(entry + 2 * (entry - stop), 4)],
        ),
        max_risk_pct=max_risk_pct,
        consensus_score=3,
        created_at=_NOW,
        expires_at=_NOW,
    )


def _short_plan(entry=150.0, stop=152.0, targets=None) -> TradePlan:
    return TradePlan(
        plan_id="test-short",
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        bias=Bias.SHORT,
        armed_setups=[ArmedSetup(setup_type=SetupType.VWAP_REJECT, confidence=0.7)],
        key_levels=KeyLevels(
            entry=entry,
            stop=stop,
            targets=targets or [round(entry - 2 * (stop - entry), 4)],
        ),
        max_risk_pct=2.0,
        consensus_score=3,
        created_at=_NOW,
        expires_at=_NOW,
    )


def _flat_plan() -> TradePlan:
    return TradePlan(
        plan_id="test-flat",
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        bias=Bias.FLAT,
        armed_setups=[],
        key_levels=None,
        max_risk_pct=2.0,
        consensus_score=1,
        created_at=_NOW,
        expires_at=_NOW,
    )


def _gw(limits=_LIMITS) -> RiskGateway:
    return RiskGateway(limits)


# ---------------------------------------------------------------------------
# FLAT plan
# ---------------------------------------------------------------------------

def test_flat_plan_always_approved():
    d = _gw().evaluate(_flat_plan(), _ACCOUNT, _MARKET)
    assert d.approved
    assert d.sized_order is None
    assert d.checks == []


# ---------------------------------------------------------------------------
# Plan geometry
# ---------------------------------------------------------------------------

def test_long_geometry_valid():
    d = _gw().evaluate(_long_plan(entry=150, stop=148, targets=[154]), _ACCOUNT, _MARKET)
    geo = next(c for c in d.checks if c.name == "plan_geometry")
    assert geo.passed


def test_long_geometry_invalid_stop_above_entry():
    # stop > entry is invalid for a long
    plan = _long_plan(entry=150, stop=152, targets=[155])
    d = _gw().evaluate(plan, _ACCOUNT, _MARKET)
    geo = next(c for c in d.checks if c.name == "plan_geometry")
    assert not geo.passed
    assert geo.reason == RejectReason.MALFORMED_PLAN
    assert not d.approved


def test_short_geometry_valid():
    d = _gw().evaluate(_short_plan(entry=150, stop=152, targets=[146]), _ACCOUNT, _MARKET)
    geo = next(c for c in d.checks if c.name == "plan_geometry")
    assert geo.passed


# ---------------------------------------------------------------------------
# Session closed
# ---------------------------------------------------------------------------

def test_session_closed_rejects():
    closed = _MARKET.model_copy(update={"session_open": False})
    d = _gw().evaluate(_long_plan(), _ACCOUNT, closed)
    sess = next(c for c in d.checks if c.name == "session_open")
    assert not sess.passed
    assert sess.reason == RejectReason.SESSION_CLOSED
    assert not d.approved


# ---------------------------------------------------------------------------
# Drawdown lock
# ---------------------------------------------------------------------------

def test_drawdown_lock_triggers():
    # 7% drawdown on a 6% limit
    acct = _ACCOUNT.model_copy(update={"equity": 93_000.0, "high_water_equity": 100_000.0})
    d = _gw().evaluate(_long_plan(), acct, _MARKET)
    dd = next(c for c in d.checks if c.name == "drawdown_lock")
    assert not dd.passed
    assert dd.reason == RejectReason.DRAWDOWN_LOCK
    assert not d.approved


def test_drawdown_just_under_limit_passes():
    acct = _ACCOUNT.model_copy(update={"equity": 94_100.0, "high_water_equity": 100_000.0})
    d = _gw().evaluate(_long_plan(), acct, _MARKET)
    dd = next(c for c in d.checks if c.name == "drawdown_lock")
    assert dd.passed


# ---------------------------------------------------------------------------
# Reward-to-risk
# ---------------------------------------------------------------------------

def test_rr_too_low_rejects():
    # RR = (151-150)/(150-148) = 0.5, below min 2.0
    plan = _long_plan(entry=150, stop=148, targets=[151])
    d = _gw().evaluate(plan, _ACCOUNT, _MARKET)
    rr = next(c for c in d.checks if c.name == "reward_to_risk")
    assert not rr.passed
    assert rr.reason == RejectReason.RR_TOO_LOW
    assert not d.approved


def test_rr_exactly_at_minimum_passes():
    # RR = 4/2 = 2.0 — meets the minimum
    plan = _long_plan(entry=150, stop=148, targets=[154])
    d = _gw().evaluate(plan, _ACCOUNT, _MARKET)
    rr = next(c for c in d.checks if c.name == "reward_to_risk")
    assert rr.passed


# ---------------------------------------------------------------------------
# Short compliance — SSR block
# ---------------------------------------------------------------------------

def test_ssr_blocks_short():
    ssr_mkt = _MARKET.model_copy(update={"ssr_active": True})
    d = _gw().evaluate(_short_plan(), _ACCOUNT, ssr_mkt)
    sc = next(c for c in d.checks if c.name == "short_compliance")
    assert not sc.passed
    assert sc.reason == RejectReason.SSR_BLOCK
    assert not d.approved


def test_ssr_does_not_block_long():
    ssr_mkt = _MARKET.model_copy(update={"ssr_active": True})
    d = _gw().evaluate(_long_plan(), _ACCOUNT, ssr_mkt)
    sc = next(c for c in d.checks if c.name == "short_compliance")
    assert sc.passed


def test_not_shortable_blocks_short():
    mkt = _MARKET.model_copy(update={"is_shortable": False})
    d = _gw().evaluate(_short_plan(), _ACCOUNT, mkt)
    sc = next(c for c in d.checks if c.name == "short_compliance")
    assert not sc.passed
    assert sc.reason == RejectReason.NO_SHORT_SPOT


# ---------------------------------------------------------------------------
# PDT block
# ---------------------------------------------------------------------------

def test_pdt_block_sub25k_over_limit():
    acct = _ACCOUNT.model_copy(update={"equity": 20_000.0, "high_water_equity": 20_000.0,
                                        "buying_power": 40_000.0, "day_trade_count_5d": 3})
    d = _gw().evaluate(_long_plan(entry=150, stop=148, targets=[154]), acct, _MARKET)
    pdt = next(c for c in d.checks if c.name == "pdt")
    assert not pdt.passed
    assert pdt.reason == RejectReason.PDT_BLOCK


def test_pdt_passes_above_25k():
    acct = _ACCOUNT.model_copy(update={"day_trade_count_5d": 5})
    d = _gw().evaluate(_long_plan(), acct, _MARKET)
    pdt = next(c for c in d.checks if c.name == "pdt")
    assert pdt.passed


# ---------------------------------------------------------------------------
# Position sizing & per-trade risk cap
# ---------------------------------------------------------------------------

def test_sizing_respects_2pct_rule():
    # entry=150, stop=148, risk/share=2, equity=100k
    # qty_by_risk  = floor(2000 / 2)   = 1000
    # qty_by_exp   = floor(30000 / 150) = 200   <- BINDING (30% exposure cap)
    # qty_by_bp    = floor(200000 / 150) = 1333
    # final qty    = min(1000, 200, 1333) = 200
    plan = _long_plan(entry=150, stop=148, targets=[154])
    d = _gw().evaluate(plan, _ACCOUNT, _MARKET)
    assert d.approved
    so: SizedOrder = d.sized_order
    assert so.qty == 200
    assert so.dollar_risk == pytest.approx(400.0)
    assert so.reward_to_risk == pytest.approx(2.0)


def test_sizing_capped_by_exposure_budget():
    # 25% already deployed; exposure budget = 5% of 100k = $5k -> 33 shares @ 150
    acct = _ACCOUNT.model_copy(update={"open_exposure_value": 25_000.0})
    plan = _long_plan(entry=150, stop=148, targets=[154])
    d = _gw().evaluate(plan, acct, _MARKET)
    assert d.approved
    assert d.sized_order.qty == 33


def test_single_unit_exceeds_risk_budget_rejects():
    # equity=$100 -> max_risk=$2; entry=150, stop=147 -> risk/share=$3 > $2
    # qty_by_risk = floor(2/3) = 0 -> per_trade_risk fails
    tiny_acct = AccountSnapshot(
        equity=100.0, cash=100.0, buying_power=200.0,
        open_exposure_value=0.0, high_water_equity=100.0,
    )
    plan = _long_plan(entry=150, stop=147, targets=[156])
    d = _gw().evaluate(plan, tiny_acct, _MARKET)
    risk_check = next(c for c in d.checks if c.name == "per_trade_risk")
    assert not risk_check.passed
    assert risk_check.reason == RejectReason.RISK_TOO_HIGH
    assert not d.approved


# ---------------------------------------------------------------------------
# Full approved path — sized order fields
# ---------------------------------------------------------------------------

def test_approved_plan_produces_sized_order():
    plan = _long_plan(entry=150, stop=148, targets=[154, 156])
    d = _gw().evaluate(plan, _ACCOUNT, _MARKET)
    assert d.approved
    so = d.sized_order
    assert so.symbol == "AAPL"
    assert so.side == Side.LONG
    assert so.entry_price == 150.0
    assert so.stop_price == 148.0
    assert so.take_profit_prices == [154, 156]
    assert so.qty > 0
