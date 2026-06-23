# D1 Trend-Following — Walk-Forward, Regime & Cross-Instrument Test

XAUUSD daily (2021–2026) and GBPUSD daily (resampled from M15, 2022–2026). Same fill model as before (next-bar open, 2bps slip, R = move / initial ATR risk). Train = entries before 2024-06; Test = entries 2024-06 → 2026-06. **These remain prototypes — read the caveats.**

## 1. Walk-forward (out-of-sample holds for gold)

| System | Full | Train (in-sample) | Test (out-of-sample) |
|---|---|---|---|
| XAUUSD Donchian-20 | +0.316 (n=42, PF 2.06) | +0.236 (n=25, PF 1.84) | +0.435 (n=17, PF 2.35) |
| XAUUSD Donchian-55 | +0.583 (n=24, PF 3.71) | +0.224 (n=15, PF 1.8) | +1.182 (n=9, PF 11.79) |
| XAUUSD EMA50/200 | +0.469 (n=52, PF 2.72) | +0.213 (n=30, PF 1.64) | +0.818 (n=22, PF 5.26) |
| GBPUSD Donchian-20 | -0.042 (n=39, PF 0.85) | +0.012 (n=19, PF 1.05) | -0.094 (n=20, PF 0.7) |
| GBPUSD Donchian-55 | -0.195 (n=30, PF 0.35) | -0.191 (n=14, PF 0.39) | -0.199 (n=16, PF 0.32) |
| GBPUSD EMA50/200 | -0.176 (n=61, PF 0.54) | -0.192 (n=26, PF 0.49) | -0.163 (n=35, PF 0.57) |

**Gold: the edge survives out-of-sample.** All three systems are positive in the test window — Donchian-20 actually improves (+0.236 train → +0.435 test), EMA50/200 +0.213 → +0.818. That's the opposite of curve-fitting, which would decay out-of-sample. *But* the test sample is small (9–22 trades), so the exact OOS figures have wide error bars — Donchian-55's +1.18R / 88% win on just 9 trades is not reliable, treat it as "positive, low-confidence."

**GBPUSD: the edge does NOT transfer.** All three systems lose on cable (Donchian-55 −0.195R, EMA −0.176R), in both train and test. Sterling chopped sideways over this window and trend-following bled in it.

## 2. Regime dependence (gold, total R by year)

| System | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| Donchian-20 | −2 | +4 | +1 | +2 | +5 | +3 |
| Donchian-55 | −1 | +2 | −1 | +3 | +7 | +3 |
| EMA50/200 | ~0 | ~0 | +1 | +11 | +15 | −2 |

Profit is **concentrated in the trending years (2024–2025)** and flat-to-slightly-negative in choppy years (2021, 2023). This is exactly trend-following's known signature: it pays during sustained trends and bleeds small in ranges. The data only goes back to 2021, so a true multi-year bear (e.g. gold 2013–2018) could not be tested — the per-year view is the closest available proxy and already shows the regime sensitivity.

## 3. Cross-instrument basket (XAU + GBP, equal weight)

| System | Trades | avg_R | Total R | Max DD (R) |
|---|---|---|---|---|
| Donchian-20 | 81 | +0.144 | +11.6 | −6.2 |
| Donchian-55 | 54 | +0.151 | +8.1 | −3.8 |
| EMA50/200 | 113 | +0.121 | +13.7 | −8.6 |

The 2-instrument basket is **positive but diluted** — gold's edge carries it while GBP drags it down (Donchian-55 falls from gold's +0.583R to +0.151R). With only two markets, one of which had no trend edge, diversification *hurt* return here. The academic diversified-trend result relies on **many (10–50+) uncorrelated trending markets**, where winners outnumber losers and volatility smooths out. Two isn't enough to show that.

## Verdict

- **Gold daily trend-following has a real, out-of-sample-robust edge** in this dataset — the single most promising result across everything tested. It is regime-dependent (needs a trend) and the OOS sample is small.
- **It is not universal**: it failed on GBPUSD. Trend-following is a *portfolio* strategy, not a single-market one.
- **Do not size up on gold alone** off small samples in a bull market.

## Honest caveats

1. Small daily samples, especially OOS (9–22 trades) → wide confidence intervals.
2. Only 5 years of gold history; no genuine bear-market sample.
3. Only 2 instruments available — EURUSD, USDJPY, NAS100, US30 were in the fetch script but never saved to disk.
4. Strong 2024–26 gold bull flatters the long side; short-side edge unconfirmed.

## Recommended next step

Build the **real diversified basket the theory needs**: re-run your `fetch_research_data.py` for the instruments it lists but didn't save (EURUSD, USDJPY, NAS100, US30), ideally with longer history, then run the same D1 Donchian/EMA suite across all of them as one equal-risk portfolio. That is the configuration under which trend-following's edge is established — and it directly tests whether gold's result generalises.
