# Cross-Sectional & Time-Series Momentum — Diversified Basket

15 daily instruments from Dukascopy, 2014–2026 (gold, silver, platinum, copper, EUR/GBP/AUD/NZD/USD-JPY/CHF/CAD, NAS100, US30, S&P500, DXY). Daily returns, inverse-vol (risk-parity) weighting, 2bps/turnover cost. This tests the one ICT-report idea with real academic backing — "long the strongest, short the weakest."

## Results

| Strategy | Lookback / rebal | Ann return | Ann vol | Sharpe | Max DD |
|---|---|---|---|---|---|
| Cross-sectional long/short | 63d / weekly | −0.5% | 9.8% | −0.06 | −34% |
| Cross-sectional long/short | 126d / monthly | +2.4% | 9.5% | 0.25 | −30% |
| **Cross-sectional long/short** | **252d / monthly** | **+5.4%** | **9.4%** | **0.56** | **−22%** |
| Cross-sectional long-only top-half | 252d / monthly | +6.3% | 7.6% | 0.81 | −12% |
| **Time-series (absolute) momentum basket** | **252d, vol-targeted** | **+2.2%** | **5.4%** | **0.41** | **−15%** |

## What this establishes

1. **Lookback is everything.** 3-month (63d) momentum is dead (Sharpe −0.06) — that horizon is noise/reversal. The edge lives at **12 months (252d)**, exactly the classic academic momentum window. This is why "fast" intraday ICT signals fail and slow momentum works.

2. **The edge is real and diversified.** A dollar-neutral 12-month cross-sectional long/short books **Sharpe 0.56** with a −22% max drawdown — and it's market-neutral, so it does *not* simply ride the gold/equity bull.

3. **It is stable across regimes — the key result.** The time-series momentum basket returns **Sharpe 0.41 in 2014–2020 AND 0.41 in 2020–2026** — two independent six-year halves, essentially identical. That cross-regime consistency is far stronger evidence than the gold-only trend result (which lived mostly in the 2024–26 bull). It also matches the published figure (~0.4 Sharpe per decade, Hurst/Ooi/Pedersen 2017) — a sanity check that we haven't overfit.

## How it compares to everything else tested

| Approach | Best result | Robustness |
|---|---|---|
| ICT CRT sweep / OB / FVG | −0.10 to −0.29R | fails everywhere |
| Intraday breakout / fast trend | ~breakeven | no |
| Gold-only daily trend-following | high avg_R, PF 2–3.7 | single market, bull-dependent, small sample |
| **Diversified 12-month momentum basket** | **Sharpe 0.41–0.56** | **stable across two independent regimes** ✅ |

The momentum basket is the **most trustworthy edge** found — not the highest headline number, but the only one that held its Sharpe across two separate six-year periods and matches independent academic evidence.

## Recommended configuration

- Universe: as broad and uncorrelated as possible (metals + FX + indices; more is better).
- Signal: 12-month (252-day) return, refreshed monthly.
- Sizing: inverse-volatility (risk parity); cap leverage.
- Form: run both the dollar-neutral long/short (0.56) and accept the long-only tilt (0.81) as a higher-return, higher-beta variant.
- This is a *portfolio* strategy — never run it on one or two instruments.

## Caveats

Sharpe ~0.4–0.6 is a real but *modest* edge — it compounds through diversification and discipline, not big single trades. 12 years / 15 instruments is decent but not huge; widen the universe further if you can. Costs modelled at 2bps/turnover; verify against your broker. Research, not financial advice.

## Run it yourself
```
python runners/run_relative_strength.py --data path/to/data/d1/*.parquet --lookback 252 --rebalance 21
```
