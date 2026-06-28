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

## Results (net of 2 bps, 2014–2026)

```
Sharpe 0.37 | ann 2.0% | vol 5.2% | maxDD -11.9%
cost sweep:  2bps 0.37 | 5bps 0.35 | 10bps 0.31      (survives)
regimes:     2015-18 0.52 | 2018-22 0.27 | 2022-26 0.32   (positive in all thirds)
breadth:     10/14 instruments individually positive
```

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
