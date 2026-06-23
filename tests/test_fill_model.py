"""Fill model tests — one test per exit mode plus key mechanics.

Each test uses a tiny synthetic bar sequence so the expected outcome is trivial
to verify by hand. We check the correct exit reason, R-multiple sign, and that
the stop-before-target rule fires correctly.
"""
from datetime import datetime, timezone

import pytest

from core.enums import Side
from core.schemas import Bar
from risk.models import SizedOrder
from backtest.fills import FillSimulator, EXIT_MODES


def _bar(ts_str, o, h, l, c, vol=1_000_000):
    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    return Bar(symbol="TEST", asset_class="equity", ts=ts, open=o, high=h, low=l, close=c, volume=vol)


def _order(stop, targets, qty=100, side=Side.LONG):
    entry = targets[0] * 0.5 + stop * 0.5  # dummy entry between stop and T1
    return SizedOrder(
        symbol="TEST", side=side, qty=qty,
        entry_price=entry, stop_price=stop,
        take_profit_prices=targets,
        dollar_risk=abs(entry - stop) * qty,
        reward_to_risk=(targets[0] - entry) / abs(entry - stop) if side is Side.LONG
        else (entry - targets[0]) / abs(entry - stop),
    )


SESSION_END = datetime.fromisoformat("2026-01-02T20:59:00").replace(tzinfo=timezone.utc)

# ------------------------------------------------------------------ breakeven

def test_breakeven_stop_exit_is_minus_one_r():
    order = _order(stop=100.0, targets=[104.0, 106.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 103, 99, 99),   # entry at open=102; low<stop->stop fires
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="breakeven")
    res = sim.simulate(order, bars, SESSION_END)
    assert res is not None
    assert len(res.exits) == 1
    assert res.exits[0].reason == "stop"
    assert res.realized_r < 0


def test_breakeven_t1_parks_stop_then_breakeven_stop():
    order = _order(stop=100.0, targets=[104.0, 108.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 105, 101, 104),  # T1 hit (high>=104); 50% out, stop->entry(102)
        _bar("2026-01-02T14:32:00+00:00", 103, 103, 101, 101),  # low<=102 (breakeven stop)
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="breakeven")
    res = sim.simulate(order, bars, SESSION_END)
    reasons = [e.reason for e in res.exits]
    assert "target_1" in reasons
    assert "breakeven_stop" in reasons
    # one partial win + one near-zero exit -> total R slightly positive or near zero
    assert res.realized_r > -0.1

# ------------------------------------------------------------------ full_target

def test_full_target_exits_100pct_at_t1():
    order = _order(stop=100.0, targets=[104.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 105, 101, 104),  # entry at 102, T1 at 104 hit
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="full_target")
    res = sim.simulate(order, bars, SESSION_END)
    assert len(res.exits) == 1
    assert res.exits[0].reason == "target_1"
    assert res.exits[0].qty == order.qty        # full position exits
    assert abs(res.realized_r - 1.0) < 0.01    # +1R: (104-102)/(104-100)*2 = 2/4*2 = 1... wait
    # entry=102, stop=100, risk_ps=2, T1=104, gain=2 -> R = 2/2 = +1R


def test_full_target_hard_stop_no_breakeven_park():
    order = _order(stop=100.0, targets=[104.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 103, 101, 102),  # entry at 102, no hit
        _bar("2026-01-02T14:32:00+00:00", 101, 101, 99, 100),   # low<stop -> full stop-out
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="full_target")
    res = sim.simulate(order, bars, SESSION_END)
    assert len(res.exits) == 1
    assert res.exits[0].reason == "stop"
    assert res.exits[0].qty == order.qty        # full position stopped
    assert abs(res.realized_r - (-1.0)) < 0.02  # -1R


def test_full_target_r_at_clean_2to1():
    # entry=102, stop=100, risk_ps=2, T1=106 (3R)... check math
    order = _order(stop=100.0, targets=[106.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 107, 101, 106),
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="full_target")
    res = sim.simulate(order, bars, SESSION_END)
    # risk_ps = |entry - stop| = |102 - 100| = 2; gain = 106-102=4; R=4/2=2.0
    assert abs(res.realized_r - 2.0) < 0.01

# ------------------------------------------------------------------ atr_trail

def test_atr_trail_ignores_targets():
    order = _order(stop=100.0, targets=[104.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 105, 101, 104),  # T1 would fire in other modes
        _bar("2026-01-02T14:32:00+00:00", 104, 106, 103, 105),  # trail rises
        _bar("2026-01-02T14:33:00+00:00", 105, 105, 102, 102),  # trail fires
    ]
    # atr=1.0: trail = bar.high - 1.0; after bar1: trail=104, bar2: trail=105, bar3: trail=105 -> low=102<105
    sim = FillSimulator(slippage_bps=0, exit_mode="atr_trail", atr_multiplier=1.0)
    res = sim.simulate(order, bars, SESSION_END, atr=1.0)
    assert len(res.exits) == 1
    assert res.exits[0].reason == "trail_stop"


def test_atr_trail_session_close_if_never_stopped():
    order = _order(stop=100.0, targets=[104.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 103, 101, 102),
        _bar("2026-01-02T14:32:00+00:00", 102, 104, 101, 103),
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="atr_trail", atr_multiplier=1.0)
    # atr=0 → trail_dist=0, trail never tightens; session close fires
    res = sim.simulate(order, bars, SESSION_END, atr=0.0)
    assert res.exits[-1].reason == "session_close"

# ------------------------------------------------------------------ mechanics

def test_stop_before_target_conservative():
    order = _order(stop=100.0, targets=[104.0])
    bars = [
        _bar("2026-01-02T14:31:00+00:00", 102, 105, 99, 102),  # both hit same bar
    ]
    sim = FillSimulator(slippage_bps=0, exit_mode="full_target", stop_before_target=True)
    res = sim.simulate(order, bars, SESSION_END)
    assert res.exits[0].reason == "stop"   # conservative: stop assumed first


def test_invalid_exit_mode_raises():
    with pytest.raises(ValueError):
        FillSimulator(exit_mode="magic")
