# Spot vs Futures — Leverage Scaling

This experiment asks: **does running on futures give an edge over spot?**

## TL;DR

For these **long-only** strategies, **futures does not provide a genuine edge**:

- At **1x leverage, futures ≈ spot** — same signals, same prices. The tiny
  improvement seen here (+5.90% vs +5.45%) comes only from lower futures trading
  fees and the fact that funding was set to zero in this test (see caveats).
- **Leverage amplifies returns *and* drawdown together.** It does not improve
  risk-adjusted return in any reliable way — it is scaling, not alpha.
- The one structural edge futures *could* provide — **shorting** to profit from
  the ~26% market drop over this window — is **not captured**, because every
  strategy here is long-only (`can_short = False`).

## Setup

- Strategy: **ElliotV5_Futures** (`strategies/ElliotV5_Futures.py`), a futures
  variant of `ElliotV5_SMA_ninja` that inherits all entry/exit logic unchanged
  and only adds a configurable `leverage()` callback (via `FT_LEVERAGE`).
  ElliotV5_SMA_ninja was chosen because it is the only strategy here that uses
  the modern Freqtrade entry/exit API — futures mode rejects the legacy
  `populate_buy_trend` / `sell_profit_only` API used by NFI/NASOS/Arcane/ElliotV8.
- Futures, isolated margin · 12 major USDT-perp pairs · 5m
- Period: 2025-02-01 → 2025-06-01 · 10,000 USDT start

## Results

| Level | Total Profit | Final Balance | Trades | Profit Factor | Sharpe | Max DD |
|-------|-------------:|--------------:|:------:|:-------------:|:------:|:------:|
| **Spot** (ElliotV5_SMA_ninja) | +5.45% | 10,544.95 | 11 | 3.35 | 0.92 | 2.25% |
| Futures 1x | +5.90% | 10,589.65 | 11 | 3.63 | 1.00 | 2.20% |
| Futures 2x | +10.73% | 11,073.20 | 13 | 10.54 | 2.98 | 1.08% |
| Futures 3x | +8.20% | 10,819.84 | 14 | 2.23 | 0.65 | 6.28% |
| Futures 5x | +17.07% | 11,706.77 | 16 | 3.42 | 1.24 | 6.30% |
| Futures 10x | +31.22% | 13,121.85 | 19 | 2.68 | 1.27 | 12.33% |

## Reading the curve

- Returns trend **up** with leverage (5.9% → 31.2%) but so does drawdown
  (2.2% → 12.3%). You are buying bigger numbers with proportionally bigger risk.
- The curve is **noisy and non-monotonic** (3x dipped below 2x). Leverage changes
  the margin each position consumes, which changes how many trades can open and
  which ones fill — so trade count drifts from 11 to 19 across the sweep. Leverage
  is therefore **not a clean multiplier** of the 1x result.
- Risk-adjusted return (Sharpe) bounces around 0.65–2.98 with no consistent
  improvement from leverage — confirming there is no free edge.

## Important caveats (why these numbers flatter futures)

1. **Synthetic futures data.** No real Bybit futures candles or funding data are
   available offline, so this test uses **spot prices as the futures OHLCV**,
   a 4h resample as the mark price, and **funding rate forced to zero**. Real
   perpetual funding is usually a *cost* for long positions, which would pull
   futures returns **below** spot. So the small 1x advantage here is an artifact.
2. **Long-only.** The ~26% downtrend is never exploited. A short-capable strategy
   is the only thing that would give futures a real directional edge — that test
   would require writing short logic, not just flipping a config flag.
3. **Liquidation risk understated.** With clean synthetic data and a wide static
   leverage tier, high-leverage liquidations are rare here; live markets with
   gaps and wicks would liquidate leveraged positions far more often.

## Conclusion

Futures **does not beat spot for these long-only strategies.** Leverage scales
P&L and risk together without improving the edge, and at 1x futures merely
matches spot (minus real funding costs, which this offline test cannot model).
The only path to a real futures edge is **enabling shorting** to trade the
downside — a strategy-logic change, left as the recommended next step.

## Reproduce

```bash
FT_LEVERAGE=3 freqtrade backtesting \
  --strategy ElliotV5_Futures --config config.json \
  --timeframe 5m --timerange 20250201- --datadir user_data/data/bybit
```

(Requires futures-format data in `user_data/data/bybit/futures/`. This offline
study generated it synthetically from spot candles.)

---

# Follow-up: Does shorting add an edge?

The conclusion above said the only real futures edge would come from **shorting**
the downtrend. So a short-enabled variant was built and tested:
**`strategies/ElliotV5_LongShort.py`** (`can_short = True`, INTERFACE_VERSION 3).
It keeps ElliotV5's dip-buying long logic and adds a **symmetric short side**:
sell rallies that spike above the EMA in a strong down-trend / overbought, cover
when price falls back below the lower EMA. Tested at 1x for a fair comparison.

## Result (futures, 1x, same window)

| Variant | Total Profit | Trades | Sharpe | Max DD |
|---------|-------------:|:------:|:------:|:------:|
| Long-only futures (ElliotV5_Futures 1x) | **+5.90%** | 11 | 1.00 | 2.20% |
| **Long + Short (ElliotV5_LongShort 1x)** | +3.94% | 42 | 0.33 | 13.75% |

### P&L split by direction (long+short run)

| Direction | Trades | Net P&L | Win % | Avg / trade |
|-----------|:------:|--------:|:-----:|------------:|
| Long  | 11 | **+595.6 USDT** | 91% | +54.1 |
| Short | 31 | **−201.3 USDT** | 77% | −6.5 |
| All   | 42 | +394.3 USDT | 81% | +9.4 |

## Verdict: shorting made it *worse*, not better

- The shorts **won 77% of the time but still lost money overall** (−201 USDT).
  High win rate, negative expectancy: the occasional losing short was large
  enough to wipe out many small winners.
- This is the classic **short-the-rally trap**. Even in a market that fell ~26%,
  the path was full of sharp relief rallies, and a mean-reversion strategy that
  shorts strength gets run over by them. Crypto bounces are violent.
- Adding shorts dragged a clean **+5.90% / 1.00 Sharpe / 2.2% DD** down to
  **+3.94% / 0.33 Sharpe / 13.75% DD** — worse on every axis.

So across this whole study: **futures provided no edge for these strategies** —
not from leverage (scales risk and return together), and not from shorting
(this symmetric short had negative expectancy). The long-only dip-buying edge was
the only thing that actually worked. A profitable short would need genuinely
different logic (e.g. trend-following breakdowns, not mean-reversion), which is a
separate research problem.
