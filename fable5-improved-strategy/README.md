# Fable 5 Improved Strategy — v2 Engines

Fixed and extended versions of the CRT, ICT P.O.3, and ICT H4 OB engines from [`GOLD_CRT_ICT_PD_Array_Strategy`](../GOLD_CRT_ICT_PD_Array_Strategy/). All bugs from v1 are patched, transaction costs are charged on every trade, and results are validated on an untouched 2025–2026 test window.

See [`IMPROVEMENTS.md`](./IMPROVEMENTS.md) for the full list of v1 issues that were fixed.

---

## What was fixed vs v1

| Fix | Detail |
|-----|--------|
| FVG look-ahead bug | v1 checked the last 5 bars of the full dataset for every trade. v2 precomputes causal rolling FVG columns. |
| Transaction costs | Round-trip spread (XAU 0.25 pip, GBP 0.8 pip) + ATR-based slippage on stop fills charged on every trade. All v2 results are NET. |
| Hindsight filters | "bull-only" and "2024+" replaced by a causal H4 SMA-200 regime filter running in real time. |
| H4 candle anchor | Dealing ranges and OBs now use NY 17:00-anchored candles (matching broker/TradingView) instead of UTC bins. |
| Walk-forward split | Parameters were never chosen on the test window (2025-01-01 onward). |
| 5-decimal rounding | v1's 3dp rounding wiped out GBPUSD risk distances in the trade logs. |
| Performance | Full 4-year M5 backtest runs in seconds (vectorised array loops, no `iterrows`). |

---

## Files

| File | Description |
|------|-------------|
| `v2_common.py` | Shared helpers: costs, NY-anchored H4 resample, causal mapping, net-R stats |
| `crt_engine_v2.py` | CRT 3-candle reversal with costs, min_rr gate, NY-anchored H4 |
| `po3_engine_v2.py` | ICT P.O.3 with fixed FVG, costs, regime filter, premium/discount, structural TP |
| `ict_ob_engine_v2.py` | ICT H4 OB + M5 MSS with costs and causal regime filter |
| `run_v2.py` | Walk-forward runner — train ≤ 2024-12-31, untouched test 2025-01-01 onward |
| `results_v2/summary.csv` | All configs × train/test, gross and net R |
| `results_v2/*_trades.csv` | Full trade logs for key configurations |
| `IMPROVEMENTS.md` | Detailed breakdown of every v1 bug and what was changed |
| `README_V2.md` | Extended technical notes on results and recommended next steps |

---

## Walk-Forward Results (NET of costs)

Train = May 2022 – Dec 2024 · Test = Jan 2025 – May 2026 (untouched)

| Strategy | Config | Period | N | WR% | Net R | PF | MaxDD |
|----------|--------|--------|---|-----|-------|----|-------|
| ICT OB | regime | train | 26 | 38.5% | +7.5 | 1.47 | 6.2 |
| **ICT OB** | **regime** | **test** | **9** | **44.4%** | **+3.9** | **1.74** | **2.1** |
| P.O.3 | regime+fvg | train | 505 | 32.3% | −17.4 | 0.95 | 69.0 |
| P.O.3 | regime+fvg | test | 257 | 33.5% | +24.6 | 1.14 | 24.4 |
| CRT | minrr2 | train | 774 | 17.6% | −217.4 | 0.73 | 228.0 |
| CRT | minrr2 | test | 432 | 19.0% | −104.2 | 0.76 | 134.8 |

### P.O.3 M15-entry variant (best result)

Uses H1 sweep wicks + M15 entries + D1 SMA-200 regime filter — cuts cost-per-trade significantly.

| Config | Period | N | WR% | Net R | PF | MaxDD |
|--------|--------|---|-----|-------|----|-------|
| **D1 regime + FVG** | **train** | **142** | **40.8%** | **+21.6** | **1.29** | **21.6** |
| **D1 regime + FVG** | **test** | **57** | **50.9%** | **+4.7** | **1.19** | **5.5** |

The only P.O.3 configuration positive net of costs in both train and test.

---

## Quick Start

```bash
cd fable5-improved-strategy

# ICT H4 OB + M5 MSS
python run_v2.py --strategy ict

# ICT Power of 3
python run_v2.py --strategy po3

# CRT
python run_v2.py --strategy crt

# P.O.3 M15-entry variant
python run_v2.py --strategy po3m15
```

Data layout expected: `data/<tf>/<SYMBOL>_<TF>.parquet` — a self-contained copy lives in the `data/` folder.

---

## Honest Read of the Results

**ICT H4 OB + regime filter is the only strategy positive net of costs in both train and test** (PF 1.47 / 1.74). Sample size is tiny (26 + 9 trades) — encouraging, not proven.

**CRT is unviable on M5 GBPUSD.** Costs average 0.20–0.23R per trade. The v1 "min_rr > 2" edge was an artifact of UTC candle anchoring and free execution.

**The cross-cutting lesson:** with M5 stops, spread alone eats 5–25% of risk on every trade. The biggest lever is larger risk distances — M15 entries, structural stops, fewer better trades.

---

*Research and educational use only — not financial advice.*
