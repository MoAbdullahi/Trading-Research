# TSMOM — Time-Series Momentum Basket

A diversified, vol-targeted **time-series (absolute) momentum** strategy
(Moskowitz–Ooi–Pedersen style) across a 14–15 instrument daily basket of metals,
FX majors, US equity indices, and the dollar index.

This is the one strategy from the broader `Trading-Research` effort that survived a
full skepticism-first kill-test cycle: a **real, broad, regime-robust,
cost-surviving edge** — modest in magnitude, and most valuable as a low-correlation
diversifier rather than a standalone outperformer.

## The strategy

| Element | Rule |
|---|---|
| Universe | XAU, XAG, XPT, COPPER, EUR, GBP, AUD, NZD, USDJPY, USDCHF, USDCAD, NAS100, US30, SPX500, DXY |
| Signal | Per instrument: **long if its own trailing 252-day return > 0, else short** |
| Sizing | Inverse-vol to a 10%/yr target (60-day vol), capped at 3× |
| Rebalance | Monthly (every 21 trading days) to cut turnover |
| Costs | Charged on turnover (2 bps default; survives to 10 bps) |
| Portfolio | Equal risk across active instruments |

## How it works

Time-series (a.k.a. *absolute*) momentum bets that **each instrument keeps doing
what it has been doing**, then diversifies that bet across an uncorrelated basket
and holds risk constant. Five steps, all causal (point-in-time):

1. **Signal — direction from each instrument's own past.** For every instrument,
   take its trailing 252-day (12-month) return. If positive → go **long**; if
   negative → go **short**. Nothing is ranked against anything else (that is what
   makes it *time-series*, not cross-sectional).
2. **Sizing — inverse volatility, constant risk.** Scale each position by
   `10% / (annualized 60-day vol)`, capped at 3×. Calm instruments get a bigger
   notional, wild ones smaller, so each contributes roughly equal *risk* rather
   than equal *dollars*.
3. **Rebalance — monthly.** Refresh signals and weights every 21 trading days and
   hold them in between. Monthly (not daily) refresh cuts turnover and keeps costs
   low without materially hurting the signal.
4. **Portfolio — equal-risk average.** The book is the average of all active
   vol-scaled positions. Diversification across ~14 instruments is the engine: many
   small, lowly-correlated trend bets net out to a smoother line than any one trade.
5. **Costs — charged on turnover.** Every rebalance pays `turnover × spread`
   (2 bps default). All headline numbers are **net** of this; the edge survives up
   to 10 bps.

**Why it works (and its limit):** trends persist slightly longer than random walk
because of how information diffuses and how investors herd — a small, real,
decades-documented premium. The limit is that the premium is *small* and has
decayed since ~2010 (visible in the 2018–22 sub-period), and on a basket this
correlated (avg |corr| 0.36) it does not beat simply being long the basket — its
value is the **0.23 correlation** to passive-long, i.e. diversification.

### Where the logic lives (files)

| File | What it implements |
|---|---|
| `src/tsmom_basket.py` | The strategy itself — the 5 steps above, end to end (signal → sizing → monthly rebalance → portfolio → net-of-cost stats). Read this first. |
| `src/tsmom_validation.py` | The proof: cost sweep (2/5/10 bps), regime split, per-instrument breadth, the passive-long **beta** comparison, and the cross-sectional variant. |
| `src/run_relative_strength.py` | The cross-sectional cousin (rank instruments against each other) — shown to be weaker (Sharpe 0.10), included for contrast. |
| `scripts/fetch_basket_d1.py` | Builds the daily basket parquets the strategy reads. |
| `reports/TSMOM_VALIDATION_REPORT.md` | Full written verdict, caveats, and the win-rate / drawdown breakdown. |

## Results (net of 2 bps, 2014–2026)

```
Sharpe 0.37 | ann 2.0% | vol 5.2% | maxDD -12.1%
cost sweep:  2bps 0.37 | 5bps 0.35 | 10bps 0.31      (survives)
regimes:     2015-18 0.52 | 2018-22 0.27 | 2022-26 0.32   (positive in all thirds)
breadth:     10/14 instruments individually positive
```

### Win rate & drawdown

Win rate rises with holding horizon — the signature of trend-following: a small
per-period edge that compounds over time.

| Horizon | Win rate |
|---|---|
| Daily bars positive | 53.2% |
| Months positive | 50.4% |
| Rolling 12-month windows positive | 59.3% |
| Calendar years positive | 69% (9 / 13 years) |

| Drawdown | Value |
|---|---|
| Max drawdown | **-12.1%** |
| Time in drawdown | 96% of days |

> The 96% "time in drawdown" looks alarming but is benign: returns are small
> (~2%/yr at ~5% vol), so the slowly-rising equity curve sits fractionally below
> its prior peak almost constantly. The drawdowns are **shallow (max -12%), just
> persistent** — the flip side of low volatility, not fragility. At Sharpe 0.37
> this is a modest **diversifier**, not a standalone outperformer.

**Honest caveats** (see `reports/TSMOM_VALIDATION_REPORT.md`):
- It did **not** beat passive-long the same basket (Sharpe 0.39) over this window —
  but it correlates only **0.23** with passive-long, so its value is *diversification*,
  not raw outperformance.
- The edge leans on the strong trenders (excluding gold+equities → 0.23). The
  cross-sectional relative-strength variant is weak (0.10): **absolute** momentum is
  the right tool for a basket this size.
- Magnitude is modest — this is what diversified TSMOM honestly is post-2010.

## Layout

```
TSMOM/
├── README.md
├── src/
│   ├── tsmom_basket.py        # core backtest (--data DIR)
│   ├── tsmom_validation.py    # cost sweep, regime split, breadth, beta, variants (--data DIR)
│   └── run_relative_strength.py   # cross-sectional rel-strength comparison
├── scripts/
│   └── fetch_basket_d1.py     # fetch daily basket from Dukascopy -> data/d1/
├── reports/
│   ├── TSMOM_VALIDATION_REPORT.md
│   └── RELATIVE_STRENGTH_REPORT.md
└── data/d1/                   # *_D1.parquet daily files (gitignored; fetch locally)
```

## Quick start

```bash
# 1) fetch the daily basket (needs: pip install dukascopy-python)
python scripts/fetch_basket_d1.py            # writes data/d1/*_D1.parquet

# 2) run the backtest
python src/tsmom_basket.py                    # defaults to ./data/d1
python src/tsmom_basket.py --data /path/to/d1

# 3) full validation (costs, regimes, breadth, beta, variants)
python src/tsmom_validation.py
```

Requirements: `pandas`, `numpy`, `pyarrow` (+ `dukascopy-python` for fetching).

## Roadmap

- **Broaden the universe** (rates, energy, ags, EM) to push avg pairwise |corr|
  from ~0.36 toward CTA-typical 0.1–0.2 — the main lever on Sharpe.
- **Combine** with passive-long and/or other low-correlation streams (the 0.23
  correlation means the blend beats either alone).
- **News / economic-calendar overlay** (to be added): an event-blackout gate
  (no rebalance into FOMC/CPI/NFP) and a correlated-exposure cap, as a *risk*
  layer — not an alpha source — pending its own drawdown-reduction backtest.
- Port into a live gateway and forward-test.
