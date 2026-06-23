"""CLI backtest runner.

Pulls real 1-min history from Alpaca for a symbol + date range, RTH-filters it
(via the asset's session profile), and replays it through the production path.

  python run_backtest.py AAPL --start 2026-05-26 --end 2026-05-30
  python run_backtest.py AAPL --start 2026-05-26 --end 2026-05-30 --live   # real agents (tokens)

Default uses the deterministic provider (free, reproducible) to validate
machinery. Use --live to spot-check actual agent judgement on a few days.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

import pandas as pd

from config.sessions import SessionProfile, profile_for
from core.enums import AssetClass
from data.alpaca_adapter import AlpacaEquityAdapter
from backtest.replay import ReplayConfig, run_replay
from backtest.providers import DeterministicSignalProvider, LiveAgentSignalProvider, PullbackSignalProvider


def rth_filter(df: pd.DataFrame, profile: SessionProfile) -> pd.DataFrame:
    """Keep only bars inside the profile's session windows (in its tz). Continuous
    assets (crypto) pass through untouched."""
    if profile.continuous:
        return df
    local = df.index.tz_convert(profile.tz)
    mask = pd.Series(False, index=df.index)
    for w in profile.windows:
        mask |= (pd.Series(local.time, index=df.index) >= w.open_t) & \
                (pd.Series(local.time, index=df.index) < w.close_t)
    return df[mask]


def _bars_to_df(bars) -> pd.DataFrame:
    rows = [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low,
             "close": b.close, "volume": b.volume} for b in bars]
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--live", action="store_true", help="use real LLM agents (costs tokens)")
    ap.add_argument("--provider", choices=["deterministic", "pullback"], default="deterministic",
                    help="entry signal provider (default: deterministic)")
    ap.add_argument("--pullback-atr", type=float, default=1.0,
                    help="pullback provider: max ATR units from support for entry (default 1.0)")
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--warmup", type=int, default=30, help="bars to skip at session open (default 30 ~ 30 min)")
    ap.add_argument("--exit-mode", choices=["breakeven", "full_target", "atr_trail"],
                    default="breakeven", help="exit strategy (default: breakeven)")
    ap.add_argument("--target-mode", choices=["structural", "r_multiple"], default="structural",
                    help="structural=use orchestrator targets as-is; r_multiple=recompute ladder from fill entry (default: structural)")
    args = ap.parse_args()

    profile = profile_for(AssetClass.EQUITY)
    adapter = AlpacaEquityAdapter()
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    bars = await adapter.get_historical_bars(args.symbol, "1Min", start, end)
    df = rth_filter(_bars_to_df(bars), profile)
    print(f"{args.symbol}: {len(df)} RTH bars  {df.index[0]} -> {df.index[-1]}")

    if args.live:
        provider = LiveAgentSignalProvider()
    elif args.provider == "pullback":
        provider = PullbackSignalProvider(pullback_atr_max=args.pullback_atr)
    else:
        provider = DeterministicSignalProvider()
    report = run_replay(args.symbol, df, provider,
                        ReplayConfig(asset_class=AssetClass.EQUITY, starting_equity=args.equity,
                                     warmup_bars=args.warmup, exit_mode=args.exit_mode,
                                     target_mode=args.target_mode))
    print(json.dumps(report.summary(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
