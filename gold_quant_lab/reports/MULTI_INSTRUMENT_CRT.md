# CRT Across Instruments — FX Majors, Metals, Indices (+ how to add crypto)

Goal: test the (improved, daily-bias-filtered) CRT beyond gold. Data on hand:
M15 only for XAUUSD & GBPUSD; daily for 13 FX/metals/indices; **no crypto**
(Dukascopy/exchanges aren't reachable from the research sandbox).

## Faithful CRT (H4 range → M15 entry) — the real test, where M15 exists

| Instrument | Baseline avg_R | + daily-bias avg_R | PF (filtered) | Trades (filtered) |
|---|---|---|---|---|
| XAUUSD | −0.115 | **+0.044** | 1.07 | 105 |
| GBPUSD | −0.327 | −0.331 | 0.57 | 137 |

**CRT does not generalize.** With the daily-bias filter it's marginally positive on gold
(+0.044R — weak, small sample, and likely negative after real spread/commission) but clearly
negative on GBP. The filter that helps gold does nothing for cable.

## Breadth check — daily analog (monthly range → daily entry), 15 instruments

| | Aggregate trades | avg_R | PF |
|---|---|---|---|
| Raw CRT | 376 | −0.063 | — |
| + daily-bias filter | 92 | +0.031 | 1.06 |

Same pattern at the aggregate (raw ≈ negative coin-flip; filter → ~breakeven). **Per-instrument
results are NOT interpretable** — only 2–10 trades each after filtering. A monthly→daily CRT just
doesn't generate enough setups; treat only the aggregate as meaningful.

## Verdict
Across everything testable, CRT is **marginal at best on gold and negative elsewhere** — no robust,
generalizable edge. Where it looks okay, it's leaning on the daily trend; and that trend edge itself
didn't transfer to GBP (cable chopped sideways, where we also found trend-following failed). This is
fully consistent with the project's conclusion: the durable edge is diversified trend/momentum, not CRT.

## How to test all FX majors + top-cap crypto faithfully (run locally)
Dukascopy carries the 7 FX majors and **BTC/USD, ETH/USD**. Two files are provided:

1. `data_fetch/fetch_pairs_m15.py` — fetches M15 for EUR/GBP/JPY/AUD/NZD/CAD/CHF + XAU + BTCUSD + ETHUSD.
   ```
   pip install dukascopy-python pandas pyarrow
   python fetch_pairs_m15.py        # -> ./data/m15/*_M15.parquet
   ```
2. `runners/run_crt_multi_m15.py` — runs the faithful H4→M15 CRT (+daily-bias) on every M15 file:
   ```
   python run_crt_multi_m15.py --dir path/to/data/m15
   ```
Once you run the fetch, share the folder and I'll produce the full multi-pair + crypto table.

*Note: crypto has real exchange volume, so for crypto the Wyckoff volume filter (which we couldn't fairly
test on gold tick-volume) becomes worth testing too.*
