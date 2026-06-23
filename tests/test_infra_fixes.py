"""Tests for the two infrastructure fixes:
  1. stop_distance floor in the gateway (Fix 2)
  2. r_multiple target-mode ladder recomputation in the fill model (Fix 1)
"""
from datetime import datetime, timezone

import pytest

from core.enums import RejectReason, Side
from core.schemas import ArmedSetup, KeyLevels, TradePlan, Bar
from core.enums import AssetClass, Bias, SetupType
from risk.gateway import RiskGateway
from risk.models import AccountSnapshot, MarketContext, RiskLimits, SizedOrder
from backtest.fills import FillSimulator, TARGET_MODES


# ------------------------------------------------------------------ helpers

def _ts():
    return datetime.now(timezone.utc)


def _plan(entry, stop, target, symbol="TEST", bias=Bias.LONG):
    now = _ts()
    return TradePlan(
        plan_id="x", symbol=symbol,
        asset_class=AssetClass.EQUITY, bias=bias,
        armed_setups=[ArmedSetup(setup_type=SetupType.VWAP_RECLAIM, confidence=0.8)],
        key_levels=KeyLevels(entry=entry, stop=stop, targets=[target]),
        max_risk_pct=1.0, consensus_score=3,
        created_at=now, expires_at=now,
    )


def _account():
    return AccountSnapshot(
        equity=100_000, cash=100_000, buying_power=400_000,
        high_water_equity=100_000,
    )


def _market(symbol="TEST"):
    return MarketContext(symbol=symbol, asset_class=AssetClass.EQUITY,
                        last_price=100.0, is_shortable=True, session_open=True)


def _bar(ts_str, o, h, l, c, vol=1_000_000):
    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    return Bar(symbol="TEST", asset_class="equity", ts=ts, open=o, high=h, low=l, close=c, volume=vol)


def _order(entry, stop, target, qty=100, side=Side.LONG):
    return SizedOrder(
        symbol="TEST", side=side, qty=qty,
        entry_price=entry, stop_price=stop,
        take_profit_prices=[target],
        dollar_risk=abs(entry - stop) * qty,
        reward_to_risk=(target - entry) / abs(entry - stop) if side is Side.LONG
        else (entry - target) / abs(entry - stop),
    )


SESSION_END = datetime.fromisoformat("2026-01-02T20:59:00").replace(tzinfo=timezone.utc)


# =========================================================== Fix 2: stop floor

class TestStopDistanceFloor:
    def _gateway(self, min_pct=0.003):
        return RiskGateway(RiskLimits(min_stop_distance_pct=min_pct))

    def test_tight_stop_rejected(self):
        # entry=100, stop=99.8 → dist=0.2% < 0.3% floor
        plan = _plan(entry=100.0, stop=99.8, target=102.0)
        dec = self._gateway(min_pct=0.003).evaluate(plan, _account(), _market())
        assert not dec.approved
        fail = dec.first_failure
        assert fail is not None
        assert fail.reason is RejectReason.STOP_TOO_TIGHT
        assert fail.name == "stop_distance"

    def test_adequate_stop_passes(self):
        # entry=100, stop=99.5 → dist=0.5% > 0.3% floor
        plan = _plan(entry=100.0, stop=99.5, target=101.0)
        dec = self._gateway(min_pct=0.003).evaluate(plan, _account(), _market())
        # may fail on other checks (e.g. RR) but not stop_distance
        stop_check = next(c for c in dec.checks if c.name == "stop_distance")
        assert stop_check.passed

    def test_floor_zero_disables_check(self):
        # setting min_stop_distance_pct=0 means any non-zero distance passes
        plan = _plan(entry=100.0, stop=99.99, target=102.0)  # 1bp stop
        dec = self._gateway(min_pct=0.0).evaluate(plan, _account(), _market())
        stop_check = next(c for c in dec.checks if c.name == "stop_distance")
        assert stop_check.passed

    def test_stop_check_fires_before_sizing(self):
        # when stop_distance fails, the gateway must not produce a sized_order
        plan = _plan(entry=100.0, stop=99.9, target=102.0)  # 10bps stop, below 30bps floor
        dec = self._gateway(min_pct=0.003).evaluate(plan, _account(), _market())
        assert not dec.approved
        assert dec.sized_order is None


# ======================================================= Fix 1: r_multiple mode

class TestTargetModeRMultiple:
    def test_invalid_target_mode_raises(self):
        with pytest.raises(ValueError):
            FillSimulator(target_mode="invalid")

    def test_target_modes_exported(self):
        assert "structural" in TARGET_MODES
        assert "r_multiple" in TARGET_MODES

    def test_structural_uses_original_target(self):
        # signal: entry=100, stop=98 → T1=104 (2R). Fill at open=101 (gap).
        # structural: T1 stays at 104 regardless of fill.
        order = _order(entry=100.0, stop=98.0, target=104.0, qty=100)
        bars = [_bar("2026-01-02T14:31:00+00:00", 101, 105, 100, 104)]
        sim = FillSimulator(slippage_bps=0, exit_mode="full_target", target_mode="structural")
        res = sim.simulate(order, bars, SESSION_END)
        # T1 at 104, fill at 101, risk_ps = |101 - 98| = 3 → realized_r = (104-101)/3 = 1.0R
        assert res is not None
        assert res.exits[0].reason == "target_1"
        assert abs(res.realized_r - 1.0) < 0.01

    def test_r_multiple_recalculates_target_from_fill(self):
        # signal: entry=100, stop=98, T1=104 (2R at signal time)
        # fill at open=101 → risk_ps=3, recomputed T1 = 101 + 2×3 = 107
        order = _order(entry=100.0, stop=98.0, target=104.0, qty=100)
        bars = [_bar("2026-01-02T14:31:00+00:00", 101, 108, 100, 107)]
        sim = FillSimulator(slippage_bps=0, exit_mode="full_target", target_mode="r_multiple")
        res = sim.simulate(order, bars, SESSION_END)
        assert res is not None
        assert res.exits[0].reason == "target_1"
        # T1 recomputed at 107, fill at 101, risk_ps=3 → R = (107-101)/3 = 2.0R
        assert abs(res.realized_r - 2.0) < 0.01

    def test_r_multiple_preserves_ladder_order(self):
        # ensure recomputed T1 < T2 (monotonic ladder preserved)
        from risk.models import SizedOrder
        order = SizedOrder(
            symbol="TEST", side=Side.LONG, qty=100,
            entry_price=100.0, stop_price=98.0,
            take_profit_prices=[104.0, 106.0],  # T1=2R, T2=3R at signal
            dollar_risk=200.0, reward_to_risk=2.0,
        )
        # fill at open=101 → risk_ps=3 → T1=107, T2=110 (still T1<T2)
        sim = FillSimulator(slippage_bps=0, exit_mode="breakeven", target_mode="r_multiple")
        bars = [
            _bar("2026-01-02T14:31:00+00:00", 101, 108, 100, 107),  # T1 hit
            _bar("2026-01-02T14:32:00+00:00", 107, 111, 106, 110),  # T2 hit
        ]
        res = sim.simulate(order, bars, SESSION_END)
        assert res is not None
        reasons = [e.reason for e in res.exits]
        assert "target_1" in reasons
        assert "target_2" in reasons
        t1_idx = reasons.index("target_1")
        t2_idx = reasons.index("target_2")
        assert t1_idx < t2_idx  # T1 must exit before T2

    def test_signal_rr_logged(self):
        # signal_rr should capture the gateway's signal-time R:R
        order = _order(entry=100.0, stop=98.0, target=104.0, qty=100)  # RR=2.0 at signal
        bars = [_bar("2026-01-02T14:31:00+00:00", 101, 105, 100, 104)]
        sim = FillSimulator(slippage_bps=0, exit_mode="full_target", target_mode="r_multiple")
        res = sim.simulate(order, bars, SESSION_END)
        assert res is not None
        assert abs(res.signal_rr - 2.0) < 0.01   # captured from order.reward_to_risk
        assert abs(res.target_r - 2.0) < 0.01    # recomputed at fill — same here since no gap in this test
