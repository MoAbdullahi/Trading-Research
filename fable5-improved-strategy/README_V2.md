# Strategy v2 — Fixed Engines + Walk-Forward Results

Everything from the review in `IMPROVEMENTS.md` implemented, plus the testable parts of the
uploaded **ICT_MultiTF_Strategy** methodology and the **Examples** chart folder.

## Files

| File | What it is |
|---|---|
| `v2_common.py` | Shared helpers: costs, NY-anchored H4 resample, causal mapping, net-R stats |
| `po3_engine_v2.py` | P.O.3 with fixed FVG, costs, regime filter, premium/discount, structural TP |
| `crt_engine_v2.py` | CRT with costs, min_rr, 5dp rounding, NY-anchored H4 |
| `ict_ob_engine_v2.py` | H4 OB + M5 MSS with costs and causal regime filter |
| `run_v2.py` | Walk-forward runner (train ≤ 2024-12-31, untouched test 2025-01-01 →) |
| `results_v2/summary.csv` | All configs × train/test, gross and net |
| `results_v2/*_trades.csv` | Full trade logs for the key configs |

## What was fixed (vs the original repo)

1. **FVG look-ahead bug** — v1 checked the last 5 bars of May 2026 for every trade
   (constant: always blocked shorts, always passed longs). v2 precomputes causal rolling
   FVG columns.
2. **Transaction costs** — round-trip spread (XAU 0.25, GBP 0.8 pip) + ATR-based slippage
   on stop fills, charged on every trade. All v2 numbers below are NET.
3. **Hindsight filters removed** — "bull-only" and "2024+" replaced by a causal H4 SMA-200
   regime filter that picks direction in real time.
4. **NY 17:00-anchored H4 candles** — dealing ranges and OBs now match broker/TradingView
   charts instead of UTC bins.
5. **Walk-forward validation** — parameters were never chosen on the test window.
6. **5-decimal rounding** (v1's 3dp wiped out GBPUSD risk distances in the logs).
7. **Fast array loops** — full 4-year M5 backtest in seconds, no iterrows.

## What was added from your uploaded methodology + Examples folder

- **Premium/Discount filter** (`pd_filter`) — longs only below the 24h range midpoint,
  shorts only above (methodology step 2).
- **Structural take-profit** (`tp_mode="structure"`) — TP at the opposite liquidity pool
  ($$$ in the example charts) instead of fixed RR (step 11).
- **HTF direction gating** (`regime_filter`) — the 4H "Direction" layer of the Examples
  timeframe hierarchy.
- **Spread buffering / cost realism** (step 9).
- Not testable with current data: M1 CHOCH execution zone entries and SMT divergence
  (needs M1 data and a correlated pair feed e.g. Silver).

## Walk-forward results (NET of costs)

Train = May 2022 – Dec 2024 · Test = Jan 2025 – May 2026 (untouched)

| Strategy | Config | Period | N | WR% | Gross R | **Net R** | PF | MaxDD |
|---|---|---|---|---|---|---|---|---|
| ICT OB | base | train | 72 | 27.8 | −0.7 | −4.7 | 0.91 | 10.2 |
| ICT OB | base | test | 15 | 40.0 | +3.5 | +3.0 | 1.32 | 2.1 |
| **ICT OB** | **regime** | **train** | **26** | **38.5** | **+8.6** | **+7.5** | **1.47** | **6.2** |
| **ICT OB** | **regime** | **test** | **9** | **44.4** | **+4.1** | **+3.9** | **1.74** | **2.1** |
| P.O.3 | v1-parity+costs | train | 974 | 30.1 | +8.9 | −78.7 | 0.89 | 95.3 |
| P.O.3 | v1-parity+costs | test | 459 | 31.2 | +27.4 | +3.5 | 1.01 | 33.4 |
| P.O.3 | regime | train | 588 | 31.3 | +23.9 | −23.8 | 0.94 | 72.3 |
| P.O.3 | regime | test | 293 | 32.8 | +36.2 | +20.8 | 1.10 | 24.2 |
| P.O.3 | regime+fvg | train | 505 | 32.3 | +20.2 | −17.4 | 0.95 | 69.0 |
| P.O.3 | regime+fvg | test | 257 | 33.5 | +37.7 | +24.6 | 1.14 | 24.4 |
| P.O.3 | regime+pd | train | 283 | 30.7 | +26.4 | +3.5 | 1.02 | 22.6 |
| P.O.3 | regime+pd | test | 150 | 26.7 | −11.6 | −21.6 | 0.82 | 38.0 |
| P.O.3 | regime+fvg+pd | train | 235 | 30.6 | +6.7 | −10.1 | 0.94 | 38.2 |
| P.O.3 | regime+fvg+pd | test | 130 | 26.2 | −10.7 | −19.5 | 0.81 | 35.1 |
| P.O.3 | regime+structTP | train | 336 | 36.3 | +6.4 | −25.8 | 0.89 | 54.4 |
| P.O.3 | regime+structTP | test | 181 | 35.9 | −4.4 | −16.2 | 0.87 | 26.5 |
| CRT | minrr0 | train | 939 | 24.5 | −45.2 | −228.8 | 0.74 | 239.7 |
| CRT | minrr0 | test | 502 | 24.5 | −18.5 | −115.7 | 0.75 | 146.9 |
| CRT | minrr2 | train | 774 | 17.6 | −36.1 | −217.4 | 0.73 | 228.0 |
| CRT | minrr2 | test | 432 | 19.0 | −4.8 | −104.2 | 0.76 | 134.8 |

## P.O.3 M15-entry variant (H1 sweeps + M15 entries + D1 regime)

Built to attack the cost problem: H1 sweep wicks give median risk ≈ $8–24 vs ≈ $5 on M5,
cutting cost-per-trade to ~0.03–0.05R. Uses `XAUUSD_H1_raw.parquet` for sweeps and
`XAUUSD_D1.parquet` (SMA-200) for the regime — run with `python run_v2.py --strategy po3m15`.

| Config | Period | N | WR% | Gross R | **Net R** | PF | MaxDD |
|---|---|---|---|---|---|---|---|
| no regime | train | 349 | 33.8 | −0.1 | −17.9 | 0.92 | 46.1 |
| no regime | test | 164 | 39.0 | −11.7 | −16.2 | 0.83 | 19.2 |
| H4-SMA200 regime | train | 155 | 29.0 | −15.1 | −23.2 | 0.77 | 25.7 |
| H4-SMA200 regime | test | 62 | 43.5 | −5.1 | −6.8 | 0.79 | 10.8 |
| D1-SMA200 regime | train | 172 | 36.6 | +24.7 | +16.2 | 1.17 | 25.6 |
| D1-SMA200 regime | test | 67 | 47.8 | +5.4 | +3.7 | 1.12 | 4.4 |
| **D1 regime + FVG** | **train** | **142** | **40.8** | **+28.2** | **+21.6** | **1.29** | **21.6** |
| **D1 regime + FVG** | **test** | **57** | **50.9** | **+5.9** | **+4.7** | **1.19** | **5.5** |

This is the first P.O.3 configuration that is **positive net of costs in both train and
test**, with respectable sample sizes (142 + 57 trades) and small drawdowns. The slow D1
SMA-200 regime matters far more than the fast H4 one — it keeps the strategy long through
gold's macro uptrend. Caveats: five configs were tried (mild selection effect), and the D1
bias means most trades are longs, so it still leans on gold's bull regime — by design,
but worth knowing.

## GBPUSD timeframe matrix (P.O.3, D1 regime, net of costs)

Same engine, four sweep×entry combos, walk-forward. JPY was requested but there is no JPY
data in `data/` — only XAUUSD and GBPUSD. Full table: `results_v2/gbp_tf_matrix.csv`.

| Combo | Config | Train Net R (PF) | Test Net R (PF) |
|---|---|---|---|
| H4→M15 | regD1 | +11.1 (1.31) | −11.3 (0.73) |
| H4→M15 | regD1+fvg | +3.6 (1.11) | −13.1 (0.65) |
| H4→M5 | regD1 | +7.6 (1.15) | −9.7 (0.82) |
| H4→M5 | regD1+fvg | +10.7 (1.23) | −7.0 (0.85) |
| H1→M15 | regD1 | −9.6 (0.88) | −6.2 (0.90) |
| H1→M15 | regD1+fvg | −6.7 (0.90) | −13.4 (0.74) |
| H1→M5 | regD1 | +6.5 (1.05) | −20.0 (0.82) |
| H1→M5 | regD1+fvg | +11.9 (1.10) | −22.5 (0.78) |

**GBPUSD fails walk-forward on every combo** — several look fine in training (PF up to
1.31) and ALL eight are negative on the untouched 2025–26 test. The gold M15-variant edge
does not transfer: it leans on a persistent directional regime (gold's macro uptrend),
which GBPUSD doesn't have. Good demonstration of why the train/test split matters — picking
"H4→M15 regD1" off the train table would have lost ~11R live.

(The engine also gained a minimum-risk guard: stop must be ≥ 2 spreads from entry; two
near-zero-risk GBP trades previously produced infinite cost ratios.)

## Honest read of the results

**ICT H4 OB + regime filter is the only strategy positive net of costs in BOTH train and
test** (PF 1.47 / 1.74). But N is tiny (26 + 9 trades) — encouraging, not proven. Note its
`sl_buffer=0.3` default came from the v1 sweep, so it carries some selection bias.

**P.O.3 has no robust net edge.** Every config loses on train net of costs. The 2025 test
profits (+20 to +25R for regime/fvg) mirror gold's trend year — same pattern the review
flagged. The now-causal FVG filter does help at the margin (improves both periods vs plain
regime), but not enough to flip train positive. The premium/discount filter looked good on
train and failed on test — exactly the kind of filter walk-forward exists to catch.
Structural TP (liquidity-pool targets) underperformed fixed 3R: pools are often too close
after the sweep, so cost-per-R rises.

**CRT is unviable on M5 GBPUSD.** Costs average 0.20–0.23R per trade on its tight stops.
The v1 "min_rr > 2" edge did not survive NY-anchored candles + costs — it was an artifact
of the UTC candle anchor and free execution.

**The cross-cutting lesson:** with sweep-wick M5 stops, spread alone eats 5–25% of risk on
every trade. The biggest single lever is *larger risk distances* — higher-TF entries (M15),
wider structural stops, or fewer better trades — not more entry filters.

## Recommended next steps

1. Grow the ICT OB + regime sample: test on more symbols (the engine is symbol-agnostic)
   and relax the impulse threshold to get N into the hundreds before trusting it.
2. Re-test P.O.3 with M15 entries / M15 stops (lower cost-per-R) instead of M5.
3. Get M1 data + a Silver feed to test the methodology's CHOCH execution layer and SMT
   divergence — the two pieces that couldn't be validated here.
4. Keep the walk-forward discipline: anything tuned on 2022–2024 must show up green on
   2025–2026 before it earns a place in the strategy.

## Reproduce

```bash
cd "Fable 5 improved strategy"
python run_v2.py --strategy ict
python run_v2.py --strategy po3
python run_v2.py --strategy crt
```

*Research/educational use only — not financial advice.*
