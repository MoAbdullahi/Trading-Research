# TSMOM Basket — Validation (the first real edge)

14-instrument daily basket (metals, FX majors, US indices, DXY), 2014-2026, via
the existing `tsmom_basket.py` logic: long if 12m return>0 else short, inverse-vol
sized to 10% target, monthly rebalance.

## Headline (net of 2bps)
```
Sharpe 0.37 | ann 2.0% | vol 5.2% | maxDD -11.9%
cost sweep:  2bps 0.37 | 5bps 0.35 | 10bps 0.31     (survives realistic costs)
regimes:     2015-18 0.52 | 2018-22 0.27 | 2022-26 0.32  (positive in ALL thirds)
```

## Validation
- **Breadth:** 10/14 instruments individually positive (NAS100 +0.54, XAG +0.40,
  SPX +0.29, COPPER +0.26 strongest). Broad, not one name.
- **Beta check (critical):** TSMOM Sharpe 0.37 vs PASSIVE long basket 0.39. Over
  this window TSMOM did NOT beat passive long — BUT corr(TSMOM, passive) = 0.23,
  so it is a near-independent return stream, valuable as a DIVERSIFIER, not a
  standalone outperformer.
- **Excluding gold+equities (10 names):** Sharpe 0.23 — edge leans on the strong
  trenders but survives without them.
- **Cross-sectional rel-strength (63d quartiles):** Sharpe 0.10 — much weaker;
  time-series (absolute) momentum is the right tool for this small, correlated set.

## Verdict
A REAL, broad, regime-robust, cost-surviving edge (unlike the ICT structural
family, which was zero-to-negative everywhere). Magnitude is MODEST (Sharpe ~0.37,
post-2010 trend-following decay visible in the 2018-22 third). Most valuable
combined with low-correlation streams rather than standalone.

## To make it compelling
1. Broaden the universe (rates, energy, ags, more index/EM) -> avg |corr| 0.36 is
   the ceiling here; a real CTA basket runs 0.1-0.2 and Sharpe rises with breadth.
2. Combine with passive-long and/or other low-corr signals (0.23 corr => the blend
   Sharpe exceeds either alone).
3. Port into the gateway and forward-test; this is the horse worth developing.


## Win rate & drawdown

Win rate is reported by holding horizon, because a vol-targeted portfolio has no
single "win %" — it depends on the period measured. The rise with horizon is the
signature of trend-following (a small per-period edge that compounds).

| Horizon | Win rate |
|---|---|
| Daily bars positive | 53.2% |
| Months positive | 50.4% |
| Rolling 12-month windows positive | 59.3% |
| Calendar years positive | 69% (9 / 13 years) |

| Drawdown | Value |
|---|---|
| Max drawdown | -12.1% |
| Time in drawdown | 96% of days |

The daily 53% is the honest hit rate — barely above a coin flip, as expected; the
edge is in winner-vs-loser size across regimes, not in being right often. The 96%
time-in-drawdown is benign: returns are small, so the slowly-rising equity curve
sits just under its prior peak almost always — the drawdowns are shallow
(max -12%), only persistent.

Per-calendar-year net return (2 bps):
2014 +5.2% | 2015 +9.3% | 2016 -5.6% | 2017 +1.0% | 2018 -1.7% | 2019 +2.6% |
2020 +4.0% | 2021 +1.3% | 2022 -0.3% | 2023 -3.8% | 2024 +5.0% | 2025 +6.6% |
2026 +3.7% (YTD).

## How the strategy works — and where the code lives

Five causal steps: (1) **signal** — long if an instrument's own trailing 252-day
return is positive, else short; (2) **sizing** — inverse-vol to a 10% target,
capped 3×; (3) **rebalance** — monthly (every 21 days); (4) **portfolio** —
equal-risk average across active instruments; (5) **costs** — turnover × spread,
charged every rebalance (all numbers net). See the README "How it works" section
for the full description.

| File | Role |
|---|---|
| `src/tsmom_basket.py` | the strategy end-to-end (read first) |
| `src/tsmom_validation.py` | cost sweep, regimes, breadth, beta, variants (this report's numbers) |
| `src/run_relative_strength.py` | cross-sectional variant (weaker, for contrast) |
| `scripts/fetch_basket_d1.py` | builds the daily basket parquets |
