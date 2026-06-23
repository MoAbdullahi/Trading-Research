"""Backtest fill model — deterministic, conservative, look-ahead-free.

Three exit modes expose different strategy hypotheses:

  breakeven  (default) — scale 50/25/25; stop -> breakeven after T1. Mirrors
                          the live execution plan. Tests the full strategy.
  full_target           — hold 100% to T1, hard stop throughout. Isolates raw
                          entry edge at a clean 2:1 R:R; no scale-out noise.
                          Breakeven win-rate threshold: 33%.
  atr_trail             — hold 100% on a trailing ATR stop; no fixed targets
                          (let the winner run until stopped or session-close).

Conservative rules that apply in every mode:
  * Entry fills at the entry bar's open (no fill on a close you already saw).
  * Entry bar is checked for stop/target after the fill (rest of bar is live).
  * Intrabar stop-before-target: if both sit inside one bar, stop assumed first.
  * Slippage on entries and stop exits (against you); targets are limit fills.
  * Hard session-end close — no overnight holds.

R-multiple is the unit: R = realized $ / (initial risk-per-share × total qty).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import Side
from core.schemas import Bar
from risk.models import SizedOrder

EXIT_MODES = ("breakeven", "full_target", "atr_trail")
TARGET_MODES = ("structural", "r_multiple")


@dataclass
class Exit:
    ts: object
    price: float
    qty: float
    reason: str  # "target_1" | "stop" | "breakeven_stop" | "trail_stop" | "session_close"


@dataclass
class TradeResult:
    symbol: str
    side: Side
    regime: str
    entry_ts: object
    entry_price: float
    initial_stop: float
    qty: float
    risk_per_share: float
    exit_mode: str = "breakeven"
    exits: list[Exit] = field(default_factory=list)
    mfe_r: float = 0.0      # max favorable excursion in R (peak unrealized profit)
    mae_r: float = 0.0      # max adverse excursion in R (peak unrealized loss, positive)
    target_r: float = 0.0   # T1 in R at fill-time prices (realized geometry)
    signal_rr: float = 0.0  # gateway's signal-time R:R (what was promised pre-fill)

    @property
    def realized_pnl(self) -> float:
        sign = 1.0 if self.side is Side.LONG else -1.0
        return sum(sign * (e.price - self.entry_price) * e.qty for e in self.exits)

    @property
    def realized_r(self) -> float:
        denom = self.risk_per_share * self.qty
        return self.realized_pnl / denom if denom > 0 else 0.0

    @property
    def exited_qty(self) -> float:
        return sum(e.qty for e in self.exits)


class FillSimulator:
    def __init__(
        self,
        slippage_bps: float = 2.0,
        commission_per_share: float = 0.0,
        scale_fractions: tuple[float, ...] = (0.5, 0.25, 0.25),
        stop_before_target: bool = True,
        exit_mode: str = "breakeven",
        atr_multiplier: float = 1.0,
        target_mode: str = "structural",
    ) -> None:
        if exit_mode not in EXIT_MODES:
            raise ValueError(f"exit_mode must be one of {EXIT_MODES}")
        if target_mode not in TARGET_MODES:
            raise ValueError(f"target_mode must be one of {TARGET_MODES}")
        self.slip = slippage_bps / 10_000.0
        self.commission = commission_per_share
        self.scale_fractions = scale_fractions
        self.stop_before_target = stop_before_target
        self.exit_mode = exit_mode
        self.atr_multiplier = atr_multiplier
        self.target_mode = target_mode

    def simulate(
        self,
        order: SizedOrder,
        future_bars: list[Bar],
        session_end_ts,
        atr: float = 0.0,
    ) -> TradeResult | None:
        if not future_bars:
            return None
        long = order.side is Side.LONG
        entry_bar = future_bars[0]
        entry = entry_bar.open * (1 + self.slip) if long else entry_bar.open * (1 - self.slip)
        risk_ps = abs(entry - order.stop_price)
        if risk_ps <= 0:
            return None

        # --- target ladder: structural (use as-is) or r_multiple (recompute from fill) ---
        raw_targets = list(order.take_profit_prices)
        if self.target_mode == "r_multiple" and self.exit_mode != "atr_trail":
            signal_risk = abs(order.entry_price - order.stop_price)
            if signal_risk > 0:
                # preserve each target's intended R-multiple, re-anchored to fill entry
                r_multiples = [
                    (t - order.entry_price) / signal_risk if long else (order.entry_price - t) / signal_risk
                    for t in raw_targets
                ]
                targets = [
                    entry + r * risk_ps if long else entry - r * risk_ps
                    for r in r_multiples
                ]
            else:
                targets = raw_targets
        else:
            targets = raw_targets

        # T1 in R at fill-time (used for MFE comparison and audit)
        t1_target_r = 0.0
        if targets and self.exit_mode != "atr_trail":
            t1 = targets[0]
            t1_target_r = ((t1 - entry) / risk_ps) if long else ((entry - t1) / risk_ps)

        res = TradeResult(
            symbol=order.symbol, side=order.side, regime="",
            entry_ts=entry_bar.ts, entry_price=entry, initial_stop=order.stop_price,
            qty=order.qty, risk_per_share=risk_ps, exit_mode=self.exit_mode,
            target_r=round(t1_target_r, 3),
            signal_rr=round(order.reward_to_risk, 3),
        )

        remaining = order.qty
        stop = order.stop_price
        t_idx = 0
        trail_stop = stop  # used only in atr_trail mode
        peak_favorable = 0.0
        peak_adverse = 0.0

        trail_dist = (atr * self.atr_multiplier) if self.exit_mode == "atr_trail" and atr > 0 else 0.0

        # walk from the entry bar onwards — entry fills at the open, then the
        # rest of that bar's range is still live (stop/target can hit same bar)
        for bar in future_bars:
            if remaining <= 0:
                break

            # --- trailing stop update (atr_trail only) ---
            if self.exit_mode == "atr_trail" and trail_dist > 0:
                if long:
                    trail_stop = max(trail_stop, bar.high - trail_dist)
                else:
                    trail_stop = min(trail_stop, bar.low + trail_dist)
                stop = trail_stop

            # --- MFE / MAE tracking (defensive: use min/max with close to guard
            # against malformed IEX bars where close can sit outside high-low) ---
            bar_high = max(bar.high, bar.close)
            bar_low = min(bar.low, bar.close)
            if long:
                peak_favorable = max(peak_favorable, (bar_high - entry) / risk_ps)
                peak_adverse = max(peak_adverse, (entry - bar_low) / risk_ps)
            else:
                peak_favorable = max(peak_favorable, (entry - bar_low) / risk_ps)
                peak_adverse = max(peak_adverse, (bar_high - entry) / risk_ps)

            # --- hit detection (same defensive bar_low/bar_high) ---
            hit_stop = (bar_low <= stop) if long else (bar_high >= stop)
            # atr_trail ignores targets; full_target and breakeven use them
            hit_target = (
                self.exit_mode != "atr_trail"
                and t_idx < len(targets)
                and ((bar_high >= targets[t_idx]) if long else (bar_low <= targets[t_idx]))
            )

            def do_stop():
                nonlocal remaining
                px = stop * (1 - self.slip) if long else stop * (1 + self.slip)
                if self.exit_mode == "atr_trail":
                    reason = "trail_stop"
                elif abs(stop - entry) < risk_ps * 0.05:
                    reason = "breakeven_stop"
                else:
                    reason = "stop"
                res.exits.append(Exit(bar.ts, px - self._fee(long), remaining, reason))
                remaining = 0.0

            def do_target():
                nonlocal remaining, t_idx, stop
                if self.exit_mode == "full_target":
                    # exit 100% at T1, hard stop stays fixed
                    res.exits.append(Exit(bar.ts, targets[t_idx] - self._fee(long),
                                         remaining, f"target_{t_idx + 1}"))
                    remaining = 0.0
                    t_idx += 1
                else:
                    # breakeven: scale 50/25/25, park stop after T1
                    frac = self.scale_fractions[min(t_idx, len(self.scale_fractions) - 1)]
                    q = min(remaining, round(order.qty * frac, 8))
                    res.exits.append(Exit(bar.ts, targets[t_idx] - self._fee(long),
                                         q, f"target_{t_idx + 1}"))
                    remaining -= q
                    if t_idx == 0:
                        stop = entry  # park stop at breakeven after T1
                    t_idx += 1

            if hit_stop and hit_target:
                (do_stop() if self.stop_before_target else (do_target(), remaining > 0 and do_stop()))
            elif hit_stop:
                do_stop()
            elif hit_target:
                do_target()

            if bar.ts >= session_end_ts and remaining > 0:
                res.exits.append(Exit(bar.ts, bar.close - self._fee(long), remaining, "session_close"))
                remaining = 0.0
                break

        if remaining > 0:
            last = future_bars[-1]
            res.exits.append(Exit(last.ts, last.close - self._fee(long), remaining, "session_close"))

        res.mfe_r = round(peak_favorable, 3)
        res.mae_r = round(peak_adverse, 3)
        return res

    def _fee(self, long: bool) -> float:
        return self.commission if long else -self.commission
