# Gold Quant Lab

A self-contained research project: testing ICT/CRT trading concepts against real
XAUUSD/FX data with proper discipline (pre-committed kill criteria, conservative
fills, walk-forward and cross-instrument validation), and building the strategies
that actually survived.

Everything here is standalone — the runners need only **Python + pandas + numpy**.

## TL;DR — what we found

| Strategy family | Result | Verdict |
|---|---|---|
| CRT sweep-reversal (OB/FVG) — all 4 timeframes | avg_R −0.10 to −0.29, PF 0.58–0.81 | ❌ no edge |
| Intraday Asian→London breakout | ~breakeven (PF 0.90) | ➖ no edge |
| Intraday / fast trend (M15–H4) | negative to flat | ❌/➖ |
| **Daily trend-following (Donchian / EMA cross)** | **avg_R +0.27 to +0.58, PF 1.8–3.7, survives out-of-sample** | ✅ real edge |
| **Cross-sectional momentum, 12-month (15-instrument basket)** | **L/S Sharpe 0.56; TSMOM Sharpe 0.41, stable across both 2014–20 & 2020–26 halves** | ✅ most robust edge |
| ICT rule *confluence* (4 rules stacked, M15) | each rule −0.15 to −0.18R; stacking ≥2/≥3 still negative (−0.14 to −0.17R) | ❌ confluence ≠ edge |

Two things survived the full gauntlet: **daily trend-following on gold** (high return, but single-market and bull-dependent) and — more robustly — **a diversified 12-month momentum basket**, whose Sharpe held identical (0.41) across two independent six-year regimes. ICT order-block / FVG / sweep methods did not survive at any timeframe.

## Folder layout

```
gold_quant_lab/
├── reports/                     ← read these
│   ├── ICT_CRT_Strategy_Report.pdf   the source ICT/MMXM concept report
│   ├── EDGE_CREATION_FRAMEWORK.md    how to turn concepts into a tested edge (start here)
│   ├── CRT_MTF_REPORT.md             CRT 4-timeframe backtest (all fail)
│   ├── GOLD_EVIDENCE_REPORT.md       breakout vs trend-following prototypes
│   ├── WALKFORWARD_REPORT.md         walk-forward + regime + cross-instrument
│   ├── RELATIVE_STRENGTH_REPORT.md   diversified 12-month momentum basket (the robust edge)
│   └── CONFLUENCE_REPORT.md          does stacking ICT rules create an edge? (no)
├── runners/                     ← reusable CLI tools (run these)
│   ├── run_gold_trend.py             Donchian / EMA-cross / Asian-breakout backtester
│   └── run_relative_strength.py      cross-sectional momentum (relative strength)
├── data_fetch/
│   └── fetch_basket_d1.py            fetch ~15 diversified daily instruments (run locally)
├── results/                     ← JSON outputs from the runs above
└── research_scripts/            ← as-run exploratory snapshots (hardcoded paths; reference only)
```

## How to use

1. **Get data** (run on your own machine — Dukascopy isn't reachable from the assistant sandbox):
   ```
   pip install dukascopy-python pandas pyarrow
   python data_fetch/fetch_basket_d1.py      # -> ./data/d1/*.parquet, ~15 instruments, back to 2014
   ```

2. **Trend-following** on any timeframe:
   ```
   python runners/run_gold_trend.py --data path/to/XAUUSD_D1.parquet --strategy donchian --lookback 55
   python runners/run_gold_trend.py --suite --d1 ... --h4 ... --h1 ...
   ```
   Walk-forward by date: add `--start 2021-06-01 --end 2024-06-01` (train) then `2024-06-01 .. 2026-06-01` (test).

3. **Relative strength / cross-sectional momentum** (needs the basket):
   ```
   python runners/run_relative_strength.py --data path/to/data/d1/*.parquet --lookback 63 --rebalance 5
   ```

## Method (the discipline that makes results trustworthy)

* Fills: entry at next bar's open, 2 bps slippage against you, intrabar stop-before-target, R = move / initial risk.
* Pre-committed kill criterion written before looking at results (≥150 trades, avg_R ≥ +0.20R, PF > 1).
* Validation: walk-forward train/test, regime (per-year) breakdown, multiple instruments.
* An "edge" = a measured, out-of-sample-positive expectancy net of costs — not a concept you trust.

## Caveats

Daily samples are small (24–52 trades); 2021–2026 was a strong gold bull; only XAUUSD + GBPUSD
were available for cross-instrument work until the basket is fetched. Paper-trade and validate
before risking capital. This is research, not financial advice.

## Next step

Fetch the basket, then test cross-sectional momentum and a mechanical "confluence" test
(measure whether stacking ICT rules actually raises expectancy vs each rule alone).
