"""Rotating-universe backtest runner.

For each trading day, runs the InPlayCriteria scanner across a symbol universe,
then replays only in-play symbols through the full production path. Aggregates
all TradeResults into a single report - this tests the actual Aziz strategy:
selection layer (gapper scan) + trigger (ORB regime rules).

Kill criterion (pre-committed 2026-06-03):
  If >=150 trades across >=20 distinct symbols over >=3 months yield avg_R < +0.10R
  using full_target exit (costs modeled at 2bps), the strategy thesis is dead.

Usage:
  python run_universe_backtest.py data/universe_liquid.txt \\
      --start 2026-01-02 --end 2026-05-29 --exit-mode full_target
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config.sessions import SessionProfile, profile_for
from core.enums import AssetClass
from data.alpaca_adapter import AlpacaEquityAdapter
from data.bar_cache import get_bars_cached
from data.scanner import InPlayCriteria, is_in_play
from backtest.replay import ReplayConfig, ReplayReport, run_replay
from backtest.providers import DeterministicSignalProvider, PullbackSignalProvider
from run_backtest import rth_filter, _bars_to_df


def load_universe(path: str) -> list[str]:
    symbols = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            sym = line.split()[0].upper()
            if sym:
                symbols.append(sym)
    return list(dict.fromkeys(symbols))  # deduplicate, preserve order


def _split_by_day(df: pd.DataFrame, profile: SessionProfile) -> dict:
    """Return {date: day_df} for each trading day in df."""
    days = df.groupby(df.index.tz_convert(profile.tz).date)
    return {d: grp for d, grp in days}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("universe", help="path to universe file (one symbol per line)")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--provider", choices=["deterministic", "pullback"], default="deterministic")
    ap.add_argument("--exit-mode", choices=["breakeven", "full_target", "atr_trail"],
                    default="full_target")
    ap.add_argument("--target-mode", choices=["structural", "r_multiple"], default="structural",
                    help="structural=use orchestrator targets; r_multiple=recompute ladder from fill entry")
    ap.add_argument("--min-gap", type=float, default=3.0, help="scanner: min gap %% (default 3.0)")
    ap.add_argument("--min-rvol", type=float, default=2.0, help="scanner: min opening RVOL (default 2.0)")
    ap.add_argument("--min-atr", type=float, default=0.50, help="scanner: min ATR $ (default 0.50)")
    ap.add_argument("--max-per-day", type=int, default=5,
                    help="max in-play symbols per day (default 5)")
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--verbose", action="store_true", help="print per-symbol scanner decisions")
    args = ap.parse_args()

    symbols = load_universe(args.universe)
    print(f"Universe: {len(symbols)} symbols")

    profile = profile_for(AssetClass.EQUITY)
    adapter = AlpacaEquityAdapter()
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    # fetch 30 extra calendar days before start for RVOL/ATR baselines
    fetch_start = start - timedelta(days=30)

    criteria = InPlayCriteria(
        min_gap_pct=args.min_gap,
        min_open_rvol=args.min_rvol,
        min_atr_dollars=args.min_atr,
    )

    if args.provider == "pullback":
        provider = PullbackSignalProvider()
    else:
        provider = DeterministicSignalProvider()

    cfg = ReplayConfig(
        asset_class=AssetClass.EQUITY,
        starting_equity=args.equity,
        warmup_bars=args.warmup,
        exit_mode=args.exit_mode,
        target_mode=args.target_mode,
    )

    # --- fetch + cache all bars up front ---
    all_dfs: dict[str, pd.DataFrame] = {}
    print(f"Fetching bars for {len(symbols)} symbols ({args.start} -> {args.end}, +30d warmup)...")
    for sym in symbols:
        try:
            bars = await get_bars_cached(adapter, sym, "1Min", fetch_start, end)
            if not bars:
                if args.verbose:
                    print(f"  {sym}: no data")
                continue
            df = rth_filter(_bars_to_df(bars), profile)
            if df.empty:
                continue
            all_dfs[sym] = df
            print(f"  {sym}: {len(df)} RTH bars")
        except Exception as exc:
            print(f"  {sym}: fetch error - {exc}")

    print(f"\nFetched {len(all_dfs)} symbols. Running scanner + replay...")

    # --- collect all trading days in the backtest range ---
    all_trades = []
    in_play_log: dict = {}  # date -> list of (symbol, stats)
    symbols_seen: set[str] = set()

    # build per-day index across all symbols
    trading_days: set = set()
    for sym, df in all_dfs.items():
        local_dates = df.index.tz_convert(profile.tz).date
        for d in local_dates:
            dt = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
            if start <= dt <= end:
                trading_days.add(d)

    for day in sorted(trading_days):
        day_symbols: list[tuple[str, float]] = []  # (symbol, gap_pct) for sorting

        for sym, df in all_dfs.items():
            local_dates = df.index.tz_convert(profile.tz).date
            day_mask = local_dates == day
            day_df = df[day_mask]
            if day_df.empty:
                continue

            # prev_bars: everything before today in the fetched frame
            today_start_utc = day_df.index[0]
            prev_df = df[df.index < today_start_utc]

            passes, stats = is_in_play(day_df, prev_df, criteria)
            if args.verbose:
                print(f"  {day} {sym}: {stats} -> {'IN PLAY' if passes else 'skip'}")

            if passes:
                day_symbols.append((sym, stats.get("gap_pct", 0.0)))
                in_play_log.setdefault(str(day), []).append({"symbol": sym, **stats})

        # cap per-day selection to max_per_day largest gappers
        day_symbols.sort(key=lambda x: x[1], reverse=True)
        day_symbols = day_symbols[: args.max_per_day]

        for sym, _ in day_symbols:
            df = all_dfs[sym]
            local_dates = df.index.tz_convert(profile.tz).date
            day_mask = local_dates == day
            day_df = df[day_mask]
            if day_df.empty:
                continue

            report = run_replay(sym, day_df, provider, cfg)
            if report.trades:
                symbols_seen.add(sym)
                all_trades.extend(report.trades)

    # --- aggregate ---
    print(f"\n{'='*60}")
    print(f"Universe backtest: {args.start} -> {args.end}")
    print(f"In-play days scanned: {len(trading_days)}")
    print(f"Total trades: {len(all_trades)} across {len(symbols_seen)} symbols")
    print(f"Kill criterion: >=150 trades / >=20 symbols / avg_R >= +0.10R")
    print()

    if all_trades:
        rs = [t.realized_r for t in all_trades]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_win = sum(wins)
        gross_loss = -sum(losses)
        cum, peak, mdd = 0.0, 0.0, 0.0
        for r in rs:
            cum += r
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)

        n = len(all_trades)
        mfes = [t.mfe_r for t in all_trades]
        avg_win = gross_win / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        reach_target = sum(1 for t in all_trades if t.target_r > 0 and t.mfe_r >= t.target_r)

        summary = {
            "trades": n,
            "symbols": len(symbols_seen),
            "win_rate": round(len(wins) / n, 3),
            "total_R": round(sum(rs), 2),
            "avg_R": round(sum(rs) / n, 3),
            "avg_win_R": round(avg_win, 3),
            "avg_loss_R": round(-avg_loss, 3),
            "best_R": round(max(rs), 2),
            "worst_R": round(min(rs), 2),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "max_drawdown_R": round(mdd, 2),
            "mfe": {
                "avg_mfe_r": round(sum(mfes) / n, 3),
                "pct_reach_target": round(reach_target / n, 3),
                "pct_mfe_above_1r": round(sum(1 for m in mfes if m >= 1.0) / n, 3),
                "pct_mfe_above_2r": round(sum(1 for m in mfes if m >= 2.0) / n, 3),
            },
            "kill_criterion_met": n >= 150 and len(symbols_seen) >= 20,
        }
        print(json.dumps(summary, indent=2))

        # per-symbol breakdown
        by_sym: dict = {}
        for t in all_trades:
            b = by_sym.setdefault(t.symbol, {"trades": 0, "total_R": 0.0, "wins": 0})
            b["trades"] += 1
            b["total_R"] = round(b["total_R"] + t.realized_r, 2)
            if t.realized_r > 0:
                b["wins"] += 1
        for sym in sorted(by_sym):
            b = by_sym[sym]
            wr = b["wins"] / b["trades"] if b["trades"] else 0
            avg = b["total_R"] / b["trades"] if b["trades"] else 0
            print(f"  {sym:8s}  {b['trades']:3d} trades  WR={wr:.1%}  total={b['total_R']:+.2f}R  avg={avg:+.3f}R")
    else:
        print("No trades generated - scanner criteria may be too strict for this date range.")

    # log scanner activity
    total_in_play_days = sum(len(v) for v in in_play_log.values())
    print(f"\nScanner: {total_in_play_days} symbol-days passed criteria across {len(in_play_log)} days")


if __name__ == "__main__":
    asyncio.run(main())
