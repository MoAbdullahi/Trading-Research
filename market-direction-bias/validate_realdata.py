"""Real-data sanity check for the bias engine.

Run this on your own machine (where Yahoo Finance is reachable):

    pip install yfinance
    python validate_realdata.py SPY BTC-USD TSLA

Or point it at a CSV with OHLC columns:

    python validate_realdata.py --csv my_bars.csv

The idea is to eyeball whether the engine's read matches what the chart actually
did over the window -- bullish bias in uptrends, bearish in downtrends, and the
ranging regime kicking in during chop. It prints the current_bias() breakdown
plus a regime/bias tally over the last ~120 bars.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from bias_engine import BiasEngine, BiasConfig


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    # yfinance returns a MultiIndex on columns for single tickers sometimes.
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def load_yf(symbol: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    return _flatten(df)


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Best-effort: title-case OHLC columns so the engine finds them.
    rename = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl in ("open", "high", "low", "close", "volume"):
            rename[c] = cl.capitalize()
    return df.rename(columns=rename)


def report(name: str, df: pd.DataFrame, config: BiasConfig = None):
    if df is None or df.empty:
        print(f"\n{name}: no data")
        return
    engine = BiasEngine(config)
    out = engine.compute(df)
    tail = out.tail(120)
    print(f"\n========== {name} ==========")
    last_close = float(df["Close"].iloc[-1])
    print(f"last close {last_close:.2f} on {df.index[-1]}")
    print(f"last 120 bars: "
          f"{(tail['bias']==1).mean():.0%} bullish / "
          f"{(tail['bias']==0).mean():.0%} neutral / "
          f"{(tail['bias']==-1).mean():.0%} bearish | "
          f"ranging {(tail['bias_regime']=='ranging').mean():.0%}")
    print(engine.current_bias(df).breakdown_table())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", default=["SPY"],
                    help="ticker symbols for yfinance")
    ap.add_argument("--csv", help="path to a CSV with OHLC columns")
    ap.add_argument("--period", default="1y")
    ap.add_argument("--interval", default="1d")
    # engine knobs so you can sweep without editing code
    ap.add_argument("--pd-band", type=float, default=0.0,
                    help="premium/discount equilibrium deadband (try 10-15)")
    ap.add_argument("--adx-threshold", type=float, default=20.0,
                    help="ADX below this = ranging regime")
    ap.add_argument("--invert-pd", action="store_true",
                    help="read premium as bullish instead of discount")
    ap.add_argument("--no-pd-regime", action="store_true",
                    help="let premium/discount vote in every regime (default: "
                         "only in ranges; abstains in trends)")
    args = ap.parse_args(argv)

    config = BiasConfig(
        pd_equilibrium_band=args.pd_band,
        adx_ranging_threshold=args.adx_threshold,
        discount_is_bullish=not args.invert_pd,
        pd_regime_aware=not args.no_pd_regime,
    )
    print(f"config: pd_band={args.pd_band}  adx_threshold={args.adx_threshold}  "
          f"discount_is_bullish={not args.invert_pd}  "
          f"pd_regime_aware={not args.no_pd_regime}")

    if args.csv:
        report(args.csv, load_csv(args.csv), config)
        return

    try:
        import yfinance  # noqa: F401
    except ImportError:
        print("yfinance not installed. Run: pip install yfinance", file=sys.stderr)
        sys.exit(1)

    for sym in (args.symbols or ["SPY"]):
        try:
            report(sym, load_yf(sym, args.period, args.interval), config)
        except Exception as e:  # noqa: BLE001
            print(f"\n{sym}: ERROR {e!r}")


if __name__ == "__main__":
    main()
