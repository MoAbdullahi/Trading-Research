# Evidence-Based Gold Prototypes — XAUUSD

Same conservative fill model as the CRT test (next-bar-open entry, 2bps slippage, intrabar stop-before-target, R = move / initial risk). Data: Dukascopy XAUUSD 2022–2026 (M15/H1/H4) and 2021–2026 (D1). These are **first-pass prototypes**, not tuned systems.

Pre-committed bar: avg_R ≥ +0.20R with profit factor > 1.0.

## Intraday — session breakout & fast trend (all FAIL, but less-bad than CRT)

| Strategy | Trades | Win rate | avg_R | Profit factor | Max DD (R) |
|---|---|---|---|---|---|
| Asian→London breakout, 2R target | 946 | 43.8% | −0.043 | 0.90 | −67.9 |
| Asian→London breakout, 1R target | 946 | 47.5% | −0.056 | 0.86 | −65.7 |
| Asian→London breakout, 1.5R (mid stop) | 946 | 40.3% | −0.099 | 0.83 | −118.5 |
| H1 Donchian-20 trail | 826 | 33% | −0.05 | 0.88 | −62 |
| H4 Donchian-20 trail | 200 | 40.0% | −0.002 | 0.99 | −17.4 |
| H4 Donchian-60 trail | 138 | 36.2% | −0.005 | 0.98 | −10.2 |

The session breakout is near breakeven (PF 0.90) — better than the CRT sweep-reversal but still not an edge after the spread. Note the pattern: **the longer the timeframe, the better trend-following gets** — M15/H1 lose, H4 is essentially flat.

## Daily — trend-following / momentum (POSITIVE edge)

| Strategy | Trades | Win rate | avg_R | Profit factor | Max DD (R) |
|---|---|---|---|---|---|
| **D1 Donchian-55 breakout, 3×ATR trail** | 24 | 62.5% | **+0.583** | **3.71** | −2.0 |
| **D1 Donchian-20 breakout, 3×ATR trail** | 42 | 50.0% | **+0.316** | **2.06** | −2.9 |
| **D1 EMA 50/200 cross** | 52 | 44.2% | **+0.270** | **1.78** | −6.1 |

All three independent daily methods clear the +0.20R bar with profit factors of 1.8–3.7 and shallow drawdowns. Buy-and-hold gold returned ~+129% over the window, so part of this is the strong 2024–26 bull run — but the controlled R-drawdowns (−2 to −6R) show the systems captured the trend with disciplined risk, not just blind long exposure.

## What this establishes

The contrast is the whole point:

- **CRT sweep-reversal / order-block / FVG** (all 4 timeframe variants): negative, PF 0.58–0.81. ❌
- **Intraday breakout & fast trend**: negative-to-breakeven. ❌/➖
- **Daily trend-following / momentum**: positive, PF ~2–3.7. ✅

This matches the literature exactly: momentum/trend has a real, replicated edge — but on **daily+ horizons**, not intraday. The SMC/ICT family has no edge at any timeframe tested here.

## Honest caveats (before risking capital)

1. **Small daily sample** (24–52 trades). Strong signal, but wide confidence intervals — needs walk-forward and out-of-sample validation.
2. **Favourable regime.** 2021–2026 was a powerful gold uptrend. The systems must be tested in a flat/bear regime (e.g. 2013–2018 gold) before trusting them.
3. **Long bias.** Most of the profit came from longs in an uptrend. Check short-side performance separately.
4. **No position sizing / compounding** modelled yet — these are R-multiple edge tests only.

## Suggested next step

Take **D1 Donchian-20/55 trend-following** forward: (a) walk-forward split (train 2021–24 / test 2024–26), (b) add a 2013–2018 bear-regime sample, (c) test the same system on the other instruments you already downloaded (EURUSD/GBPUSD/indices) — trend-following's edge is strongest as a *diversified* portfolio across uncorrelated markets, which is exactly how the academic results are generated.
