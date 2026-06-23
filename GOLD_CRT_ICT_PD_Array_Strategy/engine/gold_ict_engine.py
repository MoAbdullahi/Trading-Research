"""
GOLD ICT H4 OB + M5 MSS Backtest Engine
=========================================
Strategy logic (mirrors ICT_H4_M5_Strategy.pine exactly):

  HTF (4H) — Order Block detection
    1. Impulse up:   bull candle + body > 0.8×ATR + close > close[-2]
                     → Bull OB = body of the PRIOR bearish candle
    2. Impulse down: bear candle + body > 0.8×ATR + close < close[-2]
                     → Bear OB = body of the PRIOR bullish candle
    3. OB invalidated when LTF close breaches OB edge by 0.2×ATR

  LTF (5M / 1H) — Entry
    4. Price must be inside the active 4H OB zone (low≤OB_hi, high≥OB_lo)
    5. Session filter: London KZ (02-05 NY), London (05-08), NY AM KZ (07-10)
    6. MSS: close crosses above 10-bar recent high (bull) or below (bear)
    7. Entry at MSS candle close
    8. SL  = OB_lo - ATR×sl_buffer        (bull)  /  OB_hi + ATR×sl_buffer  (bear)
    9. TP  = entry + risk × rr_target      (bull)  /  entry - risk × rr_target (bear)
   10. OB invalidation mid-trade → close at market (close price of bar)
   11. Max hold = 48 h in LTF bars → close at market
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np

_HERE     = Path(__file__).parent
_DATA_DIR = _HERE.parent / "data"

# ── Session helpers ───────────────────────────────────────────────────────────

def _go_session(idx: pd.DatetimeIndex) -> pd.Series:
    """True for London KZ (02-05), London (05-08), NY AM KZ (07-10) in NY time."""
    ny = idx.tz_convert("America/New_York")
    h  = ny.hour
    return pd.Series(
        ((h >= 2) & (h < 5)) | ((h >= 5) & (h < 8)) | ((h >= 7) & (h < 10)),
        index=idx, dtype=bool,
    )


# ── ATR (Wilder / EMA) ───────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


# ── Data loaders ─────────────────────────────────────────────────────────────

def _ensure_tz(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


def load_h4(data_dir: Optional[Path] = None, symbol: str = "XAUUSD") -> pd.DataFrame:
    p = (data_dir or _DATA_DIR) / "h4" / f"{symbol}_H4.parquet"
    return _ensure_tz(pd.read_parquet(p))


def load_m5(data_dir: Optional[Path] = None, symbol: str = "XAUUSD") -> pd.DataFrame:
    p = (data_dir or _DATA_DIR) / "m5" / f"{symbol}_M5.parquet"
    return _ensure_tz(pd.read_parquet(p))


def load_m15(data_dir: Optional[Path] = None, symbol: str = "XAUUSD") -> pd.DataFrame:
    p = (data_dir or _DATA_DIR) / "m15" / f"{symbol}_M15.parquet"
    return _ensure_tz(pd.read_parquet(p))


def load_h1(data_dir: Optional[Path] = None, symbol: str = "XAUUSD") -> pd.DataFrame:
    """Raw 1H data — used as entry-timeframe proxy when 5M is unavailable."""
    p = (data_dir or _DATA_DIR) / "h4" / f"{symbol}_H1_raw.parquet"
    return _ensure_tz(pd.read_parquet(p))


def load_best_entry_tf(data_dir: Optional[Path] = None) -> tuple[pd.DataFrame, str]:
    """
    Return the highest-resolution entry data available.
    Priority: 5M (last 60 days only) → 1H (last ~2 years).
    Returns (dataframe, label).
    """
    try:
        m5 = load_m5(data_dir)
        if not m5.empty:
            return m5, "5M"
    except FileNotFoundError:
        pass
    h1 = load_h1(data_dir)
    return h1, "1H"


# ── H4 Order Block detection ─────────────────────────────────────────────────

def detect_h4_obs(h4: pd.DataFrame) -> pd.DataFrame:
    """
    Add OB detection columns to the 4H DataFrame.

    New columns:
      new_bull_ob  — True on the bar that creates a bull OB
      new_bear_ob  — True on the bar that creates a bear OB
      bull_ob_hi / bull_ob_lo  — price range of the bull OB candle
      bear_ob_hi / bear_ob_lo  — price range of the bear OB candle
      h4_atr       — ATR(14) on the 4H chart
    """
    h = h4.copy()
    h["h4_atr"] = _atr(h, 14)
    h["body"]   = (h["close"] - h["open"]).abs()
    h["bull"]   = h["close"] > h["open"]
    h["bear"]   = h["close"] < h["open"]

    # Impulse: strong directional candle that closes past close[-2]
    imp_up   = h["bull"] & (h["body"] > h["h4_atr"] * 0.8) & (h["close"] > h["close"].shift(2))
    imp_down = h["bear"] & (h["body"] > h["h4_atr"] * 0.8) & (h["close"] < h["close"].shift(2))

    # OB = prior candle that is the OPPOSITE colour to the impulse
    h["new_bull_ob"] = imp_up   & h["bear"].shift(1)
    h["new_bear_ob"] = imp_down & h["bull"].shift(1)

    # OB price range = body extremes of that prior candle
    prev_hi = h[["open", "close"]].shift(1).max(axis=1)
    prev_lo = h[["open", "close"]].shift(1).min(axis=1)

    h["bull_ob_hi"] = np.where(h["new_bull_ob"], prev_hi, np.nan)
    h["bull_ob_lo"] = np.where(h["new_bull_ob"], prev_lo, np.nan)
    h["bear_ob_hi"] = np.where(h["new_bear_ob"], prev_hi, np.nan)
    h["bear_ob_lo"] = np.where(h["new_bear_ob"], prev_lo, np.nan)

    return h


# ── Main backtest engine ──────────────────────────────────────────────────────

def run_backtest(
    h4:  pd.DataFrame,
    ltf: pd.DataFrame,
    *,
    rr_target:            float = 3.0,
    sl_buffer_atr:        float = 0.1,
    ob_invalid_atr:       float = 0.2,
    mss_lookback:         int   = 10,
    max_hold_bars:        int   = 576,    # 48 h × 12 bars/h for 5M
    htf_bar_size:         str   = "4h",  # HTF candle duration for close-time calc
    start_date: Optional[str]   = None,
    end_date:   Optional[str]   = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Run the ICT HTF OB + LTF MSS strategy backtest.

    Parameters
    ----------
    h4             : HTF OHLCV with UTC DatetimeIndex (4H or 1H)
    ltf            : Entry-TF OHLCV (5M, 15M, or 1H) — UTC index
    rr_target      : Risk:Reward for take-profit (default 3.0 = 3R)
    htf_bar_size   : Duration of one HTF candle e.g. "4h" or "1h"
    sl_buffer_atr  : ATR multiplier below/above OB edge for stop-loss
    ob_invalid_atr : ATR multiplier for OB invalidation threshold
    mss_lookback   : Bars to look back for MSS swing high/low
    max_hold_bars  : Maximum LTF bars before force-closing
    start_date     : Optional "YYYY-MM-DD" filter
    end_date       : Optional "YYYY-MM-DD" filter

    Returns
    -------
    trades : pd.DataFrame  (one row per closed trade)
    meta   : dict          (signal counts / skip reasons)
    """
    # Date filter
    if start_date:
        ts0 = pd.Timestamp(start_date, tz="UTC")
        h4  = h4[h4.index >= ts0]
        ltf = ltf[ltf.index >= ts0]
    if end_date:
        ts1 = pd.Timestamp(end_date, tz="UTC")
        h4  = h4[h4.index <= ts1]
        ltf = ltf[ltf.index <= ts1]

    if h4.empty or ltf.empty:
        return pd.DataFrame(), {"error": "empty data after date filter"}

    # ── Prepare 4H OB events ─────────────────────────────────────────────────
    h4 = detect_h4_obs(h4)

    # ── Prepare LTF indicator columns ────────────────────────────────────────
    ltf = ltf.copy()
    ltf["atr14"]      = _atr(ltf, 14)
    ltf["in_go"]      = _go_session(ltf.index)
    ltf["rec_hi"]     = ltf["high"].rolling(mss_lookback).max().shift(1)
    ltf["rec_lo"]     = ltf["low"].rolling(mss_lookback).min().shift(1)
    ltf["prev_close"] = ltf["close"].shift(1)

    # MSS crossover: this bar's close crosses the lookback swing level
    ltf["bull_mss"] = (ltf["close"] > ltf["rec_hi"]) & (ltf["prev_close"] <= ltf["rec_hi"])
    ltf["bear_mss"] = (ltf["close"] < ltf["rec_lo"]) & (ltf["prev_close"] >= ltf["rec_lo"])

    # ── State variables ───────────────────────────────────────────────────────
    bull_ob_active = bear_ob_active = False
    bull_ob_hi = bull_ob_lo = np.nan
    bear_ob_hi = bear_ob_lo = np.nan
    h4_atr_cur = np.nan

    in_trade  = False
    direction = None        # "bull" or "bear"
    entry_price = stop = target = np.nan
    entry_time  = None
    hold_count  = 0

    trades: list[dict] = []
    meta = {
        "h4_obs_created":   0,
        "mss_signals_seen": 0,
        "entries_taken":    0,
    }

    h4_ptr = 0
    _htf_td = pd.Timedelta(htf_bar_size)

    # ── Bar-by-bar simulation ─────────────────────────────────────────────────
    for ltf_ts, row in ltf.iterrows():
        ltf_close  = row["close"]
        ltf_hi     = row["high"]
        ltf_lo     = row["low"]
        ltf_atr    = row["atr14"]
        in_go      = bool(row["in_go"])

        # ── 1. Advance HTF state for all HTF bars that closed before this LTF bar
        while h4_ptr < len(h4):
            h4_ts    = h4.index[h4_ptr]
            h4_close_ts = h4_ts + _htf_td
            if h4_close_ts > ltf_ts:
                break

            h4_row     = h4.iloc[h4_ptr]
            h4_atr_cur = float(h4_row["h4_atr"]) if np.isfinite(h4_row["h4_atr"]) else h4_atr_cur

            if bool(h4_row["new_bull_ob"]):
                bull_ob_hi     = float(h4_row["bull_ob_hi"])
                bull_ob_lo     = float(h4_row["bull_ob_lo"])
                bull_ob_active = True
                meta["h4_obs_created"] += 1

            if bool(h4_row["new_bear_ob"]):
                bear_ob_hi     = float(h4_row["bear_ob_hi"])
                bear_ob_lo     = float(h4_row["bear_ob_lo"])
                bear_ob_active = True
                meta["h4_obs_created"] += 1

            # H4-close OB invalidation (strong structural break)
            if bull_ob_active and np.isfinite(h4_atr_cur):
                if h4_row["close"] < bull_ob_lo - h4_atr_cur * ob_invalid_atr:
                    bull_ob_active = False

            if bear_ob_active and np.isfinite(h4_atr_cur):
                if h4_row["close"] > bear_ob_hi + h4_atr_cur * ob_invalid_atr:
                    bear_ob_active = False

            h4_ptr += 1

        # ── 2. Active trade management (stop / target / max hold) ────────────
        if in_trade:
            hold_count += 1
            exited = False

            if direction == "bull":
                r_dist = entry_price - stop  # positive

                if ltf_lo <= stop and ltf_hi >= target:
                    # Ambiguous bar — conservative: stop hit first
                    _r = -1.0
                    _ep = stop
                    _reason = "stop"
                    exited = True
                elif ltf_hi >= target:
                    _r = rr_target
                    _ep = target
                    _reason = "target"
                    exited = True
                elif ltf_lo <= stop:
                    _r = -1.0
                    _ep = stop
                    _reason = "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (ltf_close - entry_price) / r_dist
                    _ep = ltf_close
                    _reason = "max_hold"
                    exited = True

                # OB invalidation on LTF close (overrides max_hold, not stop/target)
                if not exited and np.isfinite(ltf_atr):
                    if bull_ob_active and ltf_close < bull_ob_lo - ltf_atr * ob_invalid_atr:
                        bull_ob_active = False
                        _r = (ltf_close - entry_price) / r_dist
                        _ep = ltf_close
                        _reason = "ob_invalidated"
                        exited = True

            else:  # bear
                r_dist = stop - entry_price  # positive

                if ltf_hi >= stop and ltf_lo <= target:
                    _r = -1.0
                    _ep = stop
                    _reason = "stop"
                    exited = True
                elif ltf_lo <= target:
                    _r = rr_target
                    _ep = target
                    _reason = "target"
                    exited = True
                elif ltf_hi >= stop:
                    _r = -1.0
                    _ep = stop
                    _reason = "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (entry_price - ltf_close) / r_dist
                    _ep = ltf_close
                    _reason = "max_hold"
                    exited = True

                if not exited and np.isfinite(ltf_atr):
                    if bear_ob_active and ltf_close > bear_ob_hi + ltf_atr * ob_invalid_atr:
                        bear_ob_active = False
                        _r = (entry_price - ltf_close) / r_dist
                        _ep = ltf_close
                        _reason = "ob_invalidated"
                        exited = True

            if exited:
                trades.append({
                    "entry_time":  entry_time,
                    "exit_time":   ltf_ts,
                    "direction":   direction,
                    "entry_price": entry_price,
                    "stop":        stop,
                    "target":      target,
                    "exit_price":  round(_ep, 3),
                    "realized_r":  round(_r, 4),
                    "exit_reason": _reason,
                    "hold_bars":   hold_count,
                })
                in_trade = False

        # ── 3. Entry signal (only when flat, in GO session, data valid) ───────
        if in_trade or not in_go:
            continue
        if not np.isfinite(ltf_atr) or not np.isfinite(row["rec_hi"]):
            continue

        # OB invalidation check (LTF close, when not in a trade)
        if bull_ob_active and np.isfinite(ltf_atr):
            if ltf_close < bull_ob_lo - ltf_atr * ob_invalid_atr:
                bull_ob_active = False

        if bear_ob_active and np.isfinite(ltf_atr):
            if ltf_close > bear_ob_hi + ltf_atr * ob_invalid_atr:
                bear_ob_active = False

        # Bull MSS entry
        if bull_ob_active and bool(row["bull_mss"]):
            in_ob = ltf_lo <= bull_ob_hi and ltf_hi >= bull_ob_lo
            if in_ob and np.isfinite(bull_ob_lo):
                meta["mss_signals_seen"] += 1
                sl  = bull_ob_lo - ltf_atr * sl_buffer_atr
                tp  = ltf_close + (ltf_close - sl) * rr_target
                if ltf_close > sl:        # valid SL placement
                    entry_price = ltf_close
                    stop        = sl
                    target      = tp
                    entry_time  = ltf_ts
                    direction   = "bull"
                    in_trade    = True
                    hold_count  = 0
                    meta["entries_taken"] += 1
                    continue

        # Bear MSS entry
        if bear_ob_active and bool(row["bear_mss"]):
            in_ob = ltf_hi >= bear_ob_lo and ltf_lo <= bear_ob_hi
            if in_ob and np.isfinite(bear_ob_hi):
                meta["mss_signals_seen"] += 1
                sl  = bear_ob_hi + ltf_atr * sl_buffer_atr
                tp  = ltf_close - (sl - ltf_close) * rr_target
                if ltf_close < sl:        # valid SL placement
                    entry_price = ltf_close
                    stop        = sl
                    target      = tp
                    entry_time  = ltf_ts
                    direction   = "bear"
                    in_trade    = True
                    hold_count  = 0
                    meta["entries_taken"] += 1

    return pd.DataFrame(trades), meta


# ── Summary statistics ────────────────────────────────────────────────────────

def summarize(trades: pd.DataFrame) -> dict:
    """Compute performance statistics from a trades DataFrame."""
    if trades.empty:
        return {
            "n": 0, "win_rate": 0.0, "avg_r": 0.0,
            "total_r": 0.0, "pf": 0.0, "max_dd": 0.0,
            "max_loss_streak": 0, "expectancy": 0.0,
        }

    wins   = trades[trades["realized_r"] > 0]
    losses = trades[trades["realized_r"] <= 0]
    gw = wins["realized_r"].sum()
    gl = abs(losses["realized_r"].sum())
    pf = (gw / gl) if gl > 0 else float("inf")

    cum = trades["realized_r"].cumsum()
    dd  = (cum.cummax() - cum).max()

    streak = max_streak = 0
    for r in trades["realized_r"]:
        if r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    exit_counts = trades["exit_reason"].value_counts().to_dict()

    return {
        "n":               len(trades),
        "win_rate":        round(100 * len(wins) / len(trades), 1),
        "avg_r":           round(trades["realized_r"].mean(), 3),
        "total_r":         round(trades["realized_r"].sum(), 2),
        "pf":              round(pf, 2) if pf != float("inf") else 999.0,
        "max_dd":          round(dd, 2),
        "max_loss_streak": max_streak,
        "expectancy":      round(trades["realized_r"].mean() * len(trades), 1),
        "exits":           exit_counts,
    }
