"""
viz_engine.py — Instrumented backtest engine.

Records every event per trade (HTF setup, MSS, FVG/OB candidates, entries,
partials, exit) so we can visualize what the strategy did and why. Reuses
the validated logic from phase2_engine but adds an event-recording layer.

Outputs:
    - List[TradeRecord]: each record has full event timeline + bar data
      sliced for chart rendering.

Usage:
    from viz_engine import run_instrumented_backtest
    trades = run_instrumented_backtest("EURUSD", "4h", "15min", "A",
                                       start="2024-01-01", end="2024-12-31")
    # → each trade has .events, .htf_bars, .ltf_bars for visualization
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any
import pandas as pd
import numpy as np

# Reuse validated logic from existing engine
from phase2_engine import (
    load_m15, load_m5, load_ltf_source, resample_ohlc,
    atr, find_htf_triggers, SPREADS,
)

# --------------------------------------------------------------------------- #
# Data containers                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class TradeEvent:
    """One event in a trade's lifecycle (entry, partial, stop move, exit)."""
    time: pd.Timestamp
    kind: str           # "trigger", "mss", "fvg", "ob", "entry", "partial1", "partial2", "partial3", "stop_move", "exit"
    price: float | None = None
    detail: str = ""
    r_realized: float | None = None   # cumulative R at this event


@dataclass
class TradeRecord:
    """Complete record of one trade with everything needed to visualize it."""
    instrument: str
    htf_freq: str
    ltf_freq: str

    # HTF setup context
    trigger_time: pd.Timestamp
    is_bear: bool
    prev_high: float
    prev_low: float
    prev_mid: float
    sweep_extreme: float
    target: float

    # LTF entry info
    mss_idx: int | None = None
    mss_time: pd.Timestamp | None = None
    fvg_level: float | None = None
    fvg_bars: tuple | None = None   # (j-2, j) indices
    ob_level: float | None = None
    ob_bar_idx: int | None = None
    entry_type: str | None = None
    entry_price: float | None = None
    entry_time: pd.Timestamp | None = None
    stop_price: float | None = None
    r_distance: float | None = None

    # Outcome
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None    # "stop", "target", "max_hold", "partial3"
    r_total: float = 0.0
    n_partials: int = 0

    # Event timeline & bar slices for charting
    events: list[TradeEvent] = field(default_factory=list)
    htf_bars: pd.DataFrame | None = None   # H4 candles around trigger
    ltf_bars: pd.DataFrame | None = None   # M15/M5 candles during trade


# --------------------------------------------------------------------------- #
# Instrumented helpers                                                        #
# --------------------------------------------------------------------------- #
def find_mss_and_candidates(ltf_slice: pd.DataFrame, is_bear: bool, prev_mid: float,
                             max_bars: int = 12) -> dict | None:
    """Find MSS, FVG, and OB on the LTF window. Returns dict with all info."""
    if len(ltf_slice) < 5:
        return None
    bars = ltf_slice.iloc[:max_bars + 5].reset_index()

    # MSS detection
    mss_idx = -1
    if is_bear:
        ref_low = bars.loc[:3, "low"].min()
        for i in range(3, len(bars)):
            if bars.loc[i, "close"] < ref_low:
                mss_idx = i
                break
            ref_low = min(ref_low, bars.loc[i, "low"])
    else:
        ref_high = bars.loc[:3, "high"].max()
        for i in range(3, len(bars)):
            if bars.loc[i, "close"] > ref_high:
                mss_idx = i
                break
            ref_high = max(ref_high, bars.loc[i, "high"])

    if mss_idx < 0:
        return None

    # FVG: search BACKWARD from mss_idx for the LATEST PD-valid FVG
    fvg_level = None
    fvg_bars = None
    for j in range(mss_idx, 1, -1):
        if is_bear:
            if bars.loc[j-2, "low"] > bars.loc[j, "high"]:
                level = (bars.loc[j-2, "low"] + bars.loc[j, "high"]) / 2.0
                if level >= prev_mid:
                    fvg_level = level
                    fvg_bars = (j-2, j)
                    break
        else:
            if bars.loc[j-2, "high"] < bars.loc[j, "low"]:
                level = (bars.loc[j-2, "high"] + bars.loc[j, "low"]) / 2.0
                if level <= prev_mid:
                    fvg_level = level
                    fvg_bars = (j-2, j)
                    break

    # OB: search backward from mss_idx-1 for the latest opposite-color body
    ob_level = None
    ob_bar_idx = None
    for j in range(mss_idx - 1, -1, -1):
        is_bull_candle = bars.loc[j, "close"] > bars.loc[j, "open"]
        if is_bear and is_bull_candle:
            level = max(bars.loc[j, "open"], bars.loc[j, "close"])
            if level >= prev_mid:
                ob_level = level
                ob_bar_idx = j
                break
        elif (not is_bear) and (not is_bull_candle):
            level = min(bars.loc[j, "open"], bars.loc[j, "close"])
            if level <= prev_mid:
                ob_level = level
                ob_bar_idx = j
                break

    return {
        "mss_idx": mss_idx,
        "mss_time": bars.loc[mss_idx, "time"] if "time" in bars.columns else None,
        "fvg_level": fvg_level,
        "fvg_bars": fvg_bars,
        "ob_level": ob_level,
        "ob_bar_idx": ob_bar_idx,
    }


def simulate_trade_instrumented(
    ltf: pd.DataFrame, entry_time: pd.Timestamp, entry_price: float,
    stop: float, target: float, is_bear: bool,
    r_distance: float, htf_mid: float, spread: float,
    max_hold_bars: int = 192,
) -> dict:
    """Simulate trade with Scheme A partials, recording every event."""
    events: list[TradeEvent] = []
    # Partial levels (Scheme A: 50% @ 1R, 30% @ 2R, 20% to target)
    if is_bear:
        p1 = max(entry_price - 1.0 * r_distance, target)
        p2 = max(entry_price - 2.0 * r_distance, target)
        p3 = target
    else:
        p1 = min(entry_price + 1.0 * r_distance, target)
        p2 = min(entry_price + 2.0 * r_distance, target)
        p3 = target

    remaining = 1.0
    realized_r = 0.0
    n_partials = 0
    cur_stop = stop

    # Subset of LTF bars after entry
    after = ltf.loc[ltf.index >= entry_time].iloc[:max_hold_bars]
    if len(after) == 0:
        return {"events": events, "exit_reason": "no_data",
                "r_total": 0.0, "exit_time": entry_time, "exit_price": entry_price,
                "n_partials": 0}

    for idx, row in after.iterrows():
        hi, lo = row["high"], row["low"]

        # 1) Stop check first (intra-bar pessimism)
        stop_hit = (hi >= cur_stop) if is_bear else (lo <= cur_stop)
        if stop_hit:
            r_delta = ((entry_price - cur_stop) / r_distance) if is_bear else \
                      ((cur_stop - entry_price) / r_distance)
            realized_r += remaining * r_delta - remaining * (spread / r_distance)
            events.append(TradeEvent(idx, "exit", cur_stop,
                                      f"stop hit (remaining {remaining:.2f})",
                                      r_realized=realized_r))
            return {"events": events, "exit_reason": "stop",
                    "r_total": realized_r, "exit_time": idx,
                    "exit_price": cur_stop, "n_partials": n_partials}

        # 2) Partial checks — fire sequentially, can fire multiple on same bar
        p1_hit = (lo <= p1) if is_bear else (hi >= p1)
        p2_hit = (lo <= p2) if is_bear else (hi >= p2)
        p3_hit = (lo <= p3) if is_bear else (hi >= p3)

        if n_partials < 1 and p1_hit:
            r_at_p1 = ((entry_price - p1) / r_distance) if is_bear else \
                      ((p1 - entry_price) / r_distance)
            realized_r += 0.5 * r_at_p1 - 0.5 * (spread / r_distance)
            remaining -= 0.5
            n_partials = 1
            events.append(TradeEvent(idx, "partial1", p1,
                                      f"50% closed @ {r_at_p1:.2f}R",
                                      r_realized=realized_r))
            # Move stop to BE
            cur_stop = entry_price
            events.append(TradeEvent(idx, "stop_move", entry_price,
                                      "stop -> BE"))

        if n_partials < 2 and p2_hit:
            r_at_p2 = ((entry_price - p2) / r_distance) if is_bear else \
                      ((p2 - entry_price) / r_distance)
            realized_r += 0.3 * r_at_p2 - 0.3 * (spread / r_distance)
            remaining -= 0.3
            n_partials = 2
            events.append(TradeEvent(idx, "partial2", p2,
                                      f"30% closed @ {r_at_p2:.2f}R",
                                      r_realized=realized_r))
            # Move stop to 1R
            cur_stop = (entry_price - r_distance) if is_bear else (entry_price + r_distance)
            events.append(TradeEvent(idx, "stop_move", cur_stop,
                                      "stop -> 1R"))

        if n_partials < 3 and p3_hit:
            r_at_p3 = ((entry_price - p3) / r_distance) if is_bear else \
                      ((p3 - entry_price) / r_distance)
            realized_r += remaining * r_at_p3 - remaining * (spread / r_distance)
            n_partials = 3
            events.append(TradeEvent(idx, "exit", p3,
                                      f"final {remaining*100:.0f}% @ target {r_at_p3:.2f}R",
                                      r_realized=realized_r))
            return {"events": events, "exit_reason": "target",
                    "r_total": realized_r, "exit_time": idx,
                    "exit_price": p3, "n_partials": n_partials}

    # Max hold reached
    last_close = after.iloc[-1]["close"]
    r_delta = ((entry_price - last_close) / r_distance) if is_bear else \
              ((last_close - entry_price) / r_distance)
    realized_r += remaining * r_delta - remaining * (spread / r_distance)
    events.append(TradeEvent(after.index[-1], "exit", last_close,
                              f"max hold (remaining {remaining:.2f})",
                              r_realized=realized_r))
    return {"events": events, "exit_reason": "max_hold",
            "r_total": realized_r, "exit_time": after.index[-1],
            "exit_price": last_close, "n_partials": n_partials}


# --------------------------------------------------------------------------- #
# Main entry — instrumented backtest                                          #
# --------------------------------------------------------------------------- #
def run_instrumented_backtest(
    instrument: str,
    htf_freq: str = "4h",
    ltf_freq: str = "15min",
    scheme: str = "A",
    start: str | None = None,
    end: str | None = None,
    htf_window_bars: int = 6,    # H4 bars to slice for HTF chart (around trigger)
    ltf_window_bars: int = 30,   # LTF bars to slice for LTF chart (around trade)
) -> list[TradeRecord]:
    """Run a full backtest and return TradeRecord objects with event timelines."""
    m15 = load_m15(instrument)
    htf = resample_ohlc(m15, htf_freq)
    ltf_src = load_ltf_source(instrument, ltf_freq)
    ltf = resample_ohlc(ltf_src, ltf_freq)

    max_entry_window = {"5min": 36, "15min": 12, "1h": 3}.get(ltf_freq, 12)

    if start:
        start = pd.Timestamp(start)
        if start.tz is None: start = start.tz_localize("UTC")
        htf = htf.loc[htf.index >= start]
    if end:
        end = pd.Timestamp(end)
        if end.tz is None: end = end.tz_localize("UTC")
        htf = htf.loc[htf.index <= end]

    triggers = find_htf_triggers(htf)
    spread = SPREADS[instrument]
    a_ltf = atr(ltf, 14)

    records: list[TradeRecord] = []

    for ts, r in triggers.iterrows():
        is_bear = bool(r["crt_bear"])
        prev_h, prev_l = r["prev_high"], r["prev_low"]
        prev_mid = (prev_h + prev_l) / 2.0
        # Sweep extreme = the high (for bear sweep) or low (for bull sweep) of trigger candle
        sweep_extreme = r["high"] if is_bear else r["low"]
        target = prev_l if is_bear else prev_h

        # Build base record with HTF context
        rec = TradeRecord(
            instrument=instrument,
            htf_freq=htf_freq,
            ltf_freq=ltf_freq,
            trigger_time=ts,
            is_bear=is_bear,
            prev_high=prev_h,
            prev_low=prev_l,
            prev_mid=prev_mid,
            sweep_extreme=sweep_extreme,
            target=target,
        )
        rec.events.append(TradeEvent(ts, "trigger",
                                      sweep_extreme,
                                      f"{'BEAR' if is_bear else 'BULL'} sweep"))

        htf_close_time = ts + pd.Timedelta(htf_freq)
        ltf_slice = ltf.loc[ltf.index >= htf_close_time]
        if len(ltf_slice) < 5:
            continue

        # MSS + entry detection
        try:
            atr_val_ltf = a_ltf.loc[:ts].iloc[-1]
        except Exception:
            continue
        if pd.isna(atr_val_ltf) or atr_val_ltf <= 0:
            continue

        mss_info = find_mss_and_candidates(ltf_slice, is_bear, prev_mid, max_entry_window)
        if mss_info is None:
            continue   # no MSS — skip trigger (not recorded as trade)

        rec.mss_idx = mss_info["mss_idx"]
        rec.mss_time = mss_info["mss_time"]
        rec.fvg_level = mss_info["fvg_level"]
        rec.fvg_bars = mss_info["fvg_bars"]
        rec.ob_level = mss_info["ob_level"]
        rec.ob_bar_idx = mss_info["ob_bar_idx"]

        rec.events.append(TradeEvent(mss_info["mss_time"], "mss",
                                      None, f"MSS at LTF bar {mss_info['mss_idx']}"))
        if mss_info["fvg_level"] is not None:
            rec.events.append(TradeEvent(mss_info["mss_time"], "fvg",
                                          mss_info["fvg_level"],
                                          f"FVG at {mss_info['fvg_level']:.5f}"))
        if mss_info["ob_level"] is not None:
            rec.events.append(TradeEvent(mss_info["mss_time"], "ob",
                                          mss_info["ob_level"],
                                          f"OB at {mss_info['ob_level']:.5f}"))

        # Pick entry: prefer OB, fall back to FVG (matches v1.2 MQL5 logic)
        if rec.ob_level is not None:
            entry_level = rec.ob_level
            rec.entry_type = "OB"
        elif rec.fvg_level is not None:
            entry_level = rec.fvg_level
            rec.entry_type = "FVG"
        else:
            continue

        buffer = 0.1 * atr_val_ltf
        stop = sweep_extreme + buffer if is_bear else sweep_extreme - buffer
        r_distance = abs(entry_level - stop)
        if r_distance <= 0:
            continue

        rec.entry_price = entry_level
        rec.stop_price = stop
        rec.r_distance = r_distance

        # Find entry fill: when LTF retraces to limit level
        entry_window = ltf_slice.iloc[:max_entry_window]
        fill_time = None
        for idx, bar in entry_window.iterrows():
            hi, lo = bar["high"], bar["low"]
            if is_bear and hi >= entry_level:
                fill_time = idx
                break
            if (not is_bear) and lo <= entry_level:
                fill_time = idx
                break
        if fill_time is None:
            rec.exit_reason = "no_fill"
            rec.events.append(TradeEvent(htf_close_time + pd.Timedelta(hours=3),
                                          "exit", None, "no fill within window"))
            records.append(rec)
            continue

        rec.entry_time = fill_time
        rec.events.append(TradeEvent(fill_time, "entry",
                                      entry_level,
                                      f"{rec.entry_type} fill"))

        # Simulate trade
        sim = simulate_trade_instrumented(
            ltf, fill_time, entry_level, stop, target, is_bear,
            r_distance, prev_mid, spread,
            max_hold_bars=192
        )
        rec.events.extend(sim["events"])
        rec.exit_time = sim["exit_time"]
        rec.exit_price = sim["exit_price"]
        rec.exit_reason = sim["exit_reason"]
        rec.r_total = sim["r_total"]
        rec.n_partials = sim["n_partials"]

        # Slice bar data for charting
        rec.htf_bars = htf.loc[
            (htf.index >= ts - pd.Timedelta(htf_freq) * htf_window_bars) &
            (htf.index <= ts + pd.Timedelta(htf_freq) * 2)
        ].copy()
        chart_end = (rec.exit_time + pd.Timedelta(ltf_freq) * 5
                     if rec.exit_time is not None
                     else fill_time + pd.Timedelta(ltf_freq) * ltf_window_bars)
        rec.ltf_bars = ltf.loc[
            (ltf.index >= htf_close_time - pd.Timedelta(ltf_freq) * 5) &
            (ltf.index <= chart_end)
        ].copy()

        records.append(rec)

    return records


# --------------------------------------------------------------------------- #
# Summary statistics from a list of TradeRecord                               #
# --------------------------------------------------------------------------- #
def summarize_trades(trades: list[TradeRecord]) -> dict:
    """Compute aggregate statistics from a list of TradeRecord objects."""
    completed = [t for t in trades if t.exit_reason not in (None, "no_fill")]
    if not completed:
        return {"n": 0}

    rs = np.array([t.r_total for t in completed])
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    profit_factor = (wins.sum() / abs(losses.sum())) if len(losses) > 0 else float("inf")

    # Drawdown computation (per-trade cumulative)
    cum_r = np.cumsum(rs)
    peak = np.maximum.accumulate(cum_r)
    dd = peak - cum_r
    max_dd = float(dd.max())

    # Longest losing streak
    streak = 0; max_streak = 0
    for r in rs:
        if r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "n": len(completed),
        "wins": int((rs > 0).sum()),
        "losses": int((rs <= 0).sum()),
        "win_rate": round(100 * (rs > 0).mean(), 2),
        "avg_r": round(float(rs.mean()), 3),
        "total_r": round(float(rs.sum()), 2),
        "expectancy_per_trade": round(float(rs.mean()), 3),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "max_dd_r": round(max_dd, 2),
        "max_loss_streak": max_streak,
        "best_r": round(float(rs.max()), 2),
        "worst_r": round(float(rs.min()), 2),
        "n_partials_filled": int(sum(t.n_partials for t in completed)),
    }


if __name__ == "__main__":
    # Quick smoke test
    trades = run_instrumented_backtest("EURUSD", "4h", "15min", "A",
                                        start="2024-01-01", end="2024-12-31")
    print(f"Generated {len(trades)} trade records")
    completed = [t for t in trades if t.exit_reason not in (None, "no_fill")]
    print(f"  Of which {len(completed)} were filled and completed")
    print("Stats:", summarize_trades(trades))
