"""
CRT + ICT PD Array Backtest Engine  (Extended)
===============================================
Extended version of the Phase 2 engine with fully configurable parameters
for use with the interactive dashboard.

All new parameters have backward-compatible defaults that preserve
the original research behaviour.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, List
from functools import lru_cache
import pandas as pd
import numpy as np

# ── Default paths ────────────────────────────────────────────────────────────
# Looks for data in   <project_root>/data/   relative to this file's location.
# Override per-call via the data_path= argument to run_backtest().
_ENGINE_DIR   = Path(__file__).parent
_PROJECT_ROOT = _ENGINE_DIR.parent
DEFAULT_DATA_PATH = _PROJECT_ROOT.parent / "data"   # ../data  (at repo root)

# ── Spreads (price units, typical FTMO) ──────────────────────────────────────
SPREADS = {
    "EURUSD": 0.00005, "GBPUSD": 0.00008, "USDJPY": 0.008,
    "XAUUSD": 0.25,    "NAS100": 1.5,     "US30":   1.5,
}

# ── Session definitions (NY local hour ranges) ────────────────────────────────
ALL_SESSIONS = [
    "asian_kz", "asian", "london_kz", "london",
    "ny_am_kz", "london_close", "ny_pm", "off_hours",
]
GO_SESSIONS = {"asian_kz", "asian", "london_kz", "london", "ny_am_kz"}


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_path(data_path: Optional[Path]) -> Path:
    return Path(data_path) if data_path is not None else DEFAULT_DATA_PATH


@lru_cache(maxsize=24)
def _load_parquet_cached(full_path: str) -> pd.DataFrame:
    return pd.read_parquet(full_path).sort_index()


def load_m15(instrument: str, data_path=None) -> pd.DataFrame:
    p = _resolve_path(data_path) / "m15" / f"{instrument}_M15.parquet"
    return _load_parquet_cached(str(p))


def load_m5(instrument: str, data_path=None) -> pd.DataFrame:
    p = _resolve_path(data_path) / "m5" / f"{instrument}_M5.parquet"
    return _load_parquet_cached(str(p))


def load_m1(instrument: str, data_path=None) -> pd.DataFrame:
    p = _resolve_path(data_path) / "m1" / f"{instrument}_M1.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"M1 data not found at {p}. "
            "Run data_fetch/fetch_m1_data.py first."
        )
    return _load_parquet_cached(str(p))


def load_ltf_source(instrument: str, ltf_freq: str, data_path=None) -> pd.DataFrame:
    """Select highest-resolution source that covers ltf_freq."""
    if ltf_freq == "1min":
        return load_m1(instrument, data_path)
    if ltf_freq == "5min":
        return load_m5(instrument, data_path)
    return load_m15(instrument, data_path)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"],
         (df["high"] - pc).abs(),
         (df["low"]  - pc).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def resample_ohlc(src: pd.DataFrame, freq: str) -> pd.DataFrame:
    return src.resample(freq, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna(subset=["open"])


def ny_session(idx: pd.DatetimeIndex) -> pd.Series:
    ny = idx.tz_convert("America/New_York")
    h  = ny.hour
    cond   = [(h >= 20) & (h < 22), (h >= 22) | (h < 2),
              (h >= 2)  & (h < 5),  (h >= 5)  & (h < 7),
              (h >= 7)  & (h < 10), (h >= 10) & (h < 12),
              (h >= 12) & (h < 16), (h >= 16) & (h < 20)]
    labels = ["asian_kz", "asian", "london_kz", "london", "ny_am_kz",
              "london_close", "ny_pm", "off_hours"]
    return pd.Series(np.select(cond, labels, default="unknown"), index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# HTF trigger detection
# ─────────────────────────────────────────────────────────────────────────────

def find_htf_triggers(
    htf: pd.DataFrame,
    sessions: Optional[List[str]] = None,
    strong_filter: bool = True,
    min_atr_ratio: float = 0.5,
) -> pd.DataFrame:
    """
    Identify CRT manipulation candles on the HTF.

    Parameters
    ----------
    sessions        : allowed session names; None → use GO_SESSIONS
    strong_filter   : require manipulation candle to close past 0.5 midpoint
    min_atr_ratio   : prior range candle total range must be ≥ ratio × ATR(14)
    """
    allowed = set(sessions) if sessions is not None else GO_SESSIONS

    a = htf.copy()
    a["prev_high"]  = a["high"].shift(1)
    a["prev_low"]   = a["low"].shift(1)
    a["prev_mid"]   = (a["prev_high"] + a["prev_low"]) / 2.0
    a["atr14"]      = atr(a, 14)
    a["prev_atr14"] = a["atr14"].shift(1)
    a["prev_range"] = a["prev_high"] - a["prev_low"]

    a["swept_high"] = a["high"]  > a["prev_high"]
    a["swept_low"]  = a["low"]   < a["prev_low"]
    a["swept_both"] = a["swept_high"] & a["swept_low"]

    # Range candle size filter (applied to the PRIOR candle)
    a["range_ok"] = a["prev_range"] >= min_atr_ratio * a["prev_atr14"]

    if strong_filter:
        # Must close past the 0.5 midpoint (original research definition)
        a["crt_bear"] = a["swept_high"] & (a["close"] <= a["prev_mid"]) & ~a["swept_both"]
        a["crt_bull"] = a["swept_low"]  & (a["close"] >= a["prev_mid"]) & ~a["swept_both"]
    else:
        # Relaxed: just needs to sweep and close back inside range
        a["crt_bear"] = a["swept_high"] & (a["close"] < a["prev_high"]) & ~a["swept_both"]
        a["crt_bull"] = a["swept_low"]  & (a["close"] > a["prev_low"])  & ~a["swept_both"]

    a["session"] = ny_session(a.index)
    a["in_go"]   = a["session"].isin(allowed)

    return a[
        (a["crt_bear"] | a["crt_bull"]) & a["in_go"] & a["range_ok"]
    ].copy()


# ─────────────────────────────────────────────────────────────────────────────
# LTF entry detection
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EntryCandidate:
    type: str       # "FVG" or "OB"
    level: float
    valid_until: pd.Timestamp


def find_mss_and_entries(
    ltf_slice: pd.DataFrame,
    is_bear: bool,
    sweep_close_time: pd.Timestamp,
    atr_ltf: float,
    max_bars: int = 12,
    require_mss: bool = True,
    entry_pref: str = "BOTH",   # "OB", "FVG", "BOTH"
) -> List[EntryCandidate]:
    """
    Scan LTF bars for MSS, then identify FVG and/or OB candidates.

    require_mss : if False, skip MSS detection — scan full window for PD arrays
    entry_pref  : which array types to return
    """
    if len(ltf_slice) < 5:
        return []

    bars = ltf_slice.iloc[:max_bars + 5].reset_index()
    candidates: List[EntryCandidate] = []

    if require_mss:
        # ── MSS detection ─────────────────────────────────────────────────
        mss_idx = None
        if is_bear:
            ref_low = bars.loc[:3, "low"].min()
            for i in range(4, len(bars)):
                if bars.loc[i, "close"] < ref_low:
                    mss_idx = i
                    break
                ref_low = min(ref_low, bars.loc[i, "low"])
        else:
            ref_high = bars.loc[:3, "high"].max()
            for i in range(4, len(bars)):
                if bars.loc[i, "close"] > ref_high:
                    mss_idx = i
                    break
                ref_high = max(ref_high, bars.loc[i, "high"])

        if mss_idx is None or mss_idx >= len(bars) - 1:
            return []
        scan_end = mss_idx + 1  # search ONLY up to MSS bar
    else:
        # No MSS required — scan the whole window
        mss_idx  = len(bars) - 1
        scan_end = len(bars)

    expire_bar = min(mss_idx + max_bars, len(bars) - 1)
    expire_ts  = bars.loc[expire_bar, "timestamp"]

    # ── FVG search: return LATEST valid FVG (closest to MSS / end of scan) ──
    if entry_pref in ("FVG", "BOTH"):
        for j in range(scan_end - 1, 1, -1):   # search backwards → latest first
            if is_bear:
                if bars.loc[j - 2, "low"] > bars.loc[j, "high"]:
                    mid = (bars.loc[j - 2, "low"] + bars.loc[j, "high"]) / 2.0
                    candidates.append(EntryCandidate("FVG", mid, expire_ts))
                    break   # take only the latest
            else:
                if bars.loc[j - 2, "high"] < bars.loc[j, "low"]:
                    mid = (bars.loc[j - 2, "high"] + bars.loc[j, "low"]) / 2.0
                    candidates.append(EntryCandidate("FVG", mid, expire_ts))
                    break

    # ── OB: last opposite-colour candle before MSS ────────────────────────
    if entry_pref in ("OB", "BOTH"):
        for j in range(mss_idx - 1, -1, -1):
            is_bull_candle = bars.loc[j, "close"] > bars.loc[j, "open"]
            if is_bear and is_bull_candle:
                ob_level = max(bars.loc[j, "open"], bars.loc[j, "close"])
                candidates.append(EntryCandidate("OB", float(ob_level), expire_ts))
                break
            if (not is_bear) and (not is_bull_candle):
                ob_level = min(bars.loc[j, "open"], bars.loc[j, "close"])
                candidates.append(EntryCandidate("OB", float(ob_level), expire_ts))
                break

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Trade simulation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    entry_time:    pd.Timestamp
    entry_price:   float
    entry_type:    str
    direction:     str
    stop:          float
    initial_target: float
    r_distance:    float
    exit_time:     pd.Timestamp
    final_r:       float
    n_partials_hit: int
    exit_reason:   str


def simulate_trade(
    ltf: pd.DataFrame,
    entry_idx: int,
    entry_price: float,
    stop: float,
    target: float,
    direction: str,
    r_distance: float,
    htf_mid: float,
    scheme: str,
    spread: float,
    max_hold_bars: int = 192,
    stop_slippage: float = 0.0,
    # Scheme A tuning
    scheme_a_p1_r: float = 1.0,
    scheme_a_p2_r: float = 2.0,
    scheme_a_weights: Tuple[float, float, float] = (0.5, 0.3, 0.2),
) -> Tuple[Optional[TradeResult], str, int]:
    """
    Walk LTF bars forward from entry. Apply partial close per chosen scheme.
    Returns (TradeResult | None, exit_reason, n_partials).
    """
    is_bear = direction == "bear"
    bars = ltf.iloc[entry_idx: entry_idx + max_hold_bars + 1]
    if len(bars) < 2:
        return None, "no_data", 0

    w1, w2, w3 = scheme_a_weights
    # Normalise weights so they sum to 1.0
    total_w = w1 + w2 + w3
    w1, w2, w3 = w1 / total_w, w2 / total_w, w3 / total_w

    if scheme == "A":
        if is_bear:
            p1 = max(entry_price - scheme_a_p1_r * r_distance, target)
            p2 = max(entry_price - scheme_a_p2_r * r_distance, target)
            p3 = target
        else:
            p1 = min(entry_price + scheme_a_p1_r * r_distance, target)
            p2 = min(entry_price + scheme_a_p2_r * r_distance, target)
            p3 = target
        target_levels = [(p1, w1), (p2, w2), (p3, w3)]
    else:  # Scheme B — structure-based
        if is_bear:
            target_levels = [(htf_mid, 0.5), (target, 0.5)]
        else:
            target_levels = [(htf_mid, 0.5), (target, 0.5)]

    remaining       = 1.0
    realized_r      = 0.0
    n_partials      = 0
    cur_stop        = stop
    next_target_idx = 0

    for ts, bar in bars.iloc[1:].iterrows():
        hi, lo = bar["high"], bar["low"]

        # Friday / weekend close (NY 20:00)
        ny_time = ts.tz_convert("America/New_York")
        if ny_time.weekday() == 4 and ny_time.hour >= 20:
            exit_price = bar["close"] - (spread if is_bear else -spread)
            r_delta    = ((entry_price - exit_price) if is_bear
                          else (exit_price - entry_price)) / r_distance
            realized_r += remaining * r_delta
            return (TradeResult(ts, entry_price, "", direction, stop, target,
                                r_distance, ts, realized_r, n_partials, "friday_close"),
                    "friday_close", n_partials)

        # ── Stop check ─────────────────────────────────────────────────────
        if is_bear:
            if hi >= cur_stop:
                fill   = cur_stop + stop_slippage
                r_delta = (entry_price - fill) / r_distance
                realized_r += remaining * r_delta - remaining * (spread / r_distance)
                return (TradeResult(ts, entry_price, "", direction, stop, target,
                                    r_distance, ts, realized_r, n_partials, "stop"),
                        "stop", n_partials)
        else:
            if lo <= cur_stop:
                fill   = cur_stop - stop_slippage
                r_delta = (fill - entry_price) / r_distance
                realized_r += remaining * r_delta - remaining * (spread / r_distance)
                return (TradeResult(ts, entry_price, "", direction, stop, target,
                                    r_distance, ts, realized_r, n_partials, "stop"),
                        "stop", n_partials)

        # ── Partial target checks ──────────────────────────────────────────
        while next_target_idx < len(target_levels):
            tgt_price, tgt_weight = target_levels[next_target_idx]
            hit = ((is_bear and lo <= tgt_price) or
                   ((not is_bear) and hi >= tgt_price))
            if not hit:
                break

            r_at_partial = ((entry_price - tgt_price) if is_bear
                             else (tgt_price - entry_price)) / r_distance
            realized_r += tgt_weight * r_at_partial - tgt_weight * (spread / r_distance)
            remaining  -= tgt_weight
            n_partials += 1

            # Stop management
            if scheme == "A":
                if next_target_idx == 0:
                    cur_stop = entry_price                        # move to BE
                elif next_target_idx == 1:
                    r1 = scheme_a_p1_r * r_distance
                    cur_stop = (entry_price - r1 if is_bear
                                else entry_price + r1)           # trail to P1
            else:
                if next_target_idx == 0:
                    cur_stop = entry_price

            next_target_idx += 1
            if remaining <= 1e-6:
                return (TradeResult(ts, entry_price, "", direction, stop, target,
                                    r_distance, ts, realized_r, n_partials, "all_targets"),
                        "all_targets", n_partials)

    # Max hold
    last_bar   = bars.iloc[-1]
    exit_price = last_bar["close"] - (spread if is_bear else -spread)
    r_delta    = ((entry_price - exit_price) if is_bear
                  else (exit_price - entry_price)) / r_distance
    realized_r += remaining * r_delta
    return (TradeResult(last_bar.name, entry_price, "", direction, stop, target,
                        r_distance, last_bar.name, realized_r, n_partials, "max_hold"),
            "max_hold", n_partials)


# ─────────────────────────────────────────────────────────────────────────────
# Main backtest runner
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(
    instrument: str,
    htf_freq: str,
    ltf_freq: str,
    scheme: str,
    # ── NEW configurable parameters ──────────────────────────────────────
    sessions: Optional[List[str]] = None,           # None → GO_SESSIONS
    strong_filter: bool = True,
    min_atr_ratio: float = 0.5,
    entry_pref: str = "BOTH",                       # "OB" | "FVG" | "BOTH"
    require_mss: bool = True,
    require_pd_filter: bool = True,
    stop_buffer_atr: float = 0.1,
    scheme_a_p1_r: float = 1.0,
    scheme_a_p2_r: float = 2.0,
    scheme_a_weights: Tuple[float, float, float] = (0.5, 0.3, 0.2),
    # ── Existing parameters (backward-compat) ────────────────────────────
    max_entry_window_ltf: Optional[int] = None,
    spread_multiplier: float = 1.0,
    stop_slippage_atr: float = 0.0,
    start_date=None,    # str "YYYY-MM-DD", date, or None
    end_date=None,
    start_year=None,    # kept for backward compat
    end_year=None,
    data_path=None,     # override default data directory
):
    """
    Run a single instrument × timeframe × scheme backtest.

    Returns
    -------
    trades : pd.DataFrame   — one row per completed trade
    skipped : dict          — rejection reason counts
    """
    # ── Load & resample data ──────────────────────────────────────────────
    m15     = load_m15(instrument, data_path)
    htf     = resample_ohlc(m15, htf_freq)
    ltf_src = load_ltf_source(instrument, ltf_freq, data_path)
    ltf     = resample_ohlc(ltf_src, ltf_freq)

    # Time-consistent entry window: 3 hours regardless of LTF bar size
    if max_entry_window_ltf is None:
        bars_per_hour = {"1min": 60, "5min": 12, "15min": 4, "1h": 1}
        max_entry_window_ltf = 3 * bars_per_hour.get(ltf_freq, 4)

    # ── HTF triggers ─────────────────────────────────────────────────────
    triggers = find_htf_triggers(
        htf,
        sessions=sessions,
        strong_filter=strong_filter,
        min_atr_ratio=min_atr_ratio,
    )

    # ── Date filtering ────────────────────────────────────────────────────
    if start_date is not None:
        triggers = triggers[triggers.index >= pd.Timestamp(start_date, tz="UTC")]
    elif start_year is not None:
        triggers = triggers[triggers.index.year >= start_year]

    if end_date is not None:
        triggers = triggers[triggers.index <= pd.Timestamp(end_date, tz="UTC")]
    elif end_year is not None:
        triggers = triggers[triggers.index.year <= end_year]

    spread  = SPREADS.get(instrument, 0.0001) * spread_multiplier
    a_ltf   = atr(ltf, 14)

    trades  = []
    skipped = {
        "no_mss": 0, "no_candidate": 0, "not_filled": 0,
        "premium_discount_fail": 0, "atr_nan": 0,
    }

    for ts, r in triggers.iterrows():
        is_bear      = bool(r["crt_bear"])
        sweep_extreme = r["high"] if is_bear else r["low"]
        mid          = r["prev_mid"]
        target       = r["prev_low"] if is_bear else r["prev_high"]

        try:
            atr_val_ltf = a_ltf.loc[:ts].iloc[-1]
        except Exception:
            skipped["atr_nan"] += 1
            continue
        if not np.isfinite(atr_val_ltf) or atr_val_ltf == 0:
            skipped["atr_nan"] += 1
            continue

        stop   = sweep_extreme + stop_buffer_atr * atr_val_ltf if is_bear \
                 else sweep_extreme - stop_buffer_atr * atr_val_ltf

        # Slice LTF after HTF candle close
        htf_close_time = ts + pd.tseries.frequencies.to_offset(htf_freq)
        ltf_slice = ltf.loc[ltf.index >= htf_close_time]
        if len(ltf_slice) < 5:
            skipped["no_candidate"] += 1
            continue

        candidates = find_mss_and_entries(
            ltf_slice, is_bear, ts, atr_val_ltf,
            max_bars=max_entry_window_ltf,
            require_mss=require_mss,
            entry_pref=entry_pref,
        )
        if not candidates:
            skipped["no_mss"] += 1
            continue

        # Premium / discount filter
        if require_pd_filter:
            valid_c = [c for c in candidates
                       if (is_bear and c.level >= mid) or
                          ((not is_bear) and c.level <= mid)]
        else:
            valid_c = candidates

        if not valid_c:
            skipped["premium_discount_fail"] += 1
            continue

        # Limit-order fill simulation
        entry_window = ltf_slice.iloc[:max_entry_window_ltf + 10]
        filled = None
        for bar_ts, bar in entry_window.iterrows():
            hi, lo = bar["high"], bar["low"]
            for c in valid_c:
                if is_bear and hi >= c.level:
                    filled = (bar_ts, c)
                    break
                if (not is_bear) and lo <= c.level:
                    filled = (bar_ts, c)
                    break
            if filled:
                break

        if not filled:
            skipped["not_filled"] += 1
            continue

        entry_ts, entry_c = filled
        entry_price = entry_c.level

        if is_bear  and stop <= entry_price:
            skipped["no_candidate"] += 1; continue
        if (not is_bear) and stop >= entry_price:
            skipped["no_candidate"] += 1; continue

        r_distance = abs(entry_price - stop)

        # Max hold in LTF bars
        bars_per_hour = {"1min": 60, "5min": 12, "15min": 4, "1h": 1}
        bph = bars_per_hour.get(ltf_freq, 4)
        max_hold_bars = 48 * bph   # 48 hours expressed in LTF bars

        try:
            entry_idx = ltf.index.get_loc(entry_ts)
        except KeyError:
            continue

        stop_slip = stop_slippage_atr * atr_val_ltf
        result, reason, n_partials = simulate_trade(
            ltf, entry_idx, entry_price, stop, target,
            "bear" if is_bear else "bull",
            r_distance, mid, scheme, spread,
            max_hold_bars=max_hold_bars,
            stop_slippage=stop_slip,
            scheme_a_p1_r=scheme_a_p1_r,
            scheme_a_p2_r=scheme_a_p2_r,
            scheme_a_weights=scheme_a_weights,
        )
        if result is None:
            continue
        result.entry_type = entry_c.type

        trades.append({
            "trigger_time":  ts,
            "session":       r["session"],
            "direction":     result.direction,
            "entry_time":    entry_ts,
            "entry_type":    entry_c.type,
            "entry_price":   entry_price,
            "stop":          stop,
            "target":        target,
            "htf_mid":       mid,
            "r_distance":    r_distance,
            "exit_time":     result.exit_time,
            "exit_reason":   reason,
            "n_partials":    n_partials,
            "realized_r":    round(result.final_r, 3),
        })

    return pd.DataFrame(trades), skipped


def summarize(trades: pd.DataFrame) -> dict:
    """Compute summary statistics from a trades DataFrame."""
    if len(trades) == 0:
        return {"n": 0, "win_rate": 0, "avg_r": 0, "total_r": 0,
                "pf": 0, "max_dd": 0, "max_streak_loss": 0, "expectancy": 0}

    wins   = trades[trades["realized_r"] > 0]
    losses = trades[trades["realized_r"] <= 0]
    gross_win  = wins["realized_r"].sum()
    gross_loss = abs(losses["realized_r"].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    cum = trades["realized_r"].cumsum()
    dd  = (cum.cummax() - cum).max()

    streak = max_streak = 0
    for rv in trades["realized_r"]:
        if rv <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "n":               len(trades),
        "win_rate":        round(100 * len(wins) / len(trades), 1),
        "avg_r":           round(trades["realized_r"].mean(), 3),
        "total_r":         round(trades["realized_r"].sum(), 2),
        "pf":              round(pf, 2) if pf != float("inf") else 999,
        "max_dd":          round(dd, 2),
        "max_streak_loss": max_streak,
        "expectancy":      round(trades["realized_r"].mean() * len(trades), 1),
    }
