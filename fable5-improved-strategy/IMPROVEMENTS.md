# Strategy Review — Bugs, Validity Issues & Improvements

Analysis of the three engines and all trade logs (June 2026).

---

## 1. Critical bug: the FVG filter is broken (look-ahead + constant)

`engine/po3_engine.py` calls `_fvg_present(m5["high"], m5["low"], direction)` with the **entire 4-year series**, not data up to the current bar. The function inspects `iloc[-5:]` — the last 5 bars of **May 2026** — on every call. Verified:

```
_fvg_present(m5.high, m5.low, 'bear')  -> False   (always — blocks ALL shorts)
_fvg_present(m5.high, m5.low, 'bull')  -> True    (always — passes ALL longs)
```

So `--fvg` never checks for an FVG. It is a constant long-only filter using future data. The README finding "FVG confluence improves quality (30.5% → 37.9% WR)" is invalid — it's the bull-only effect in disguise.

**Fix:** precompute FVG presence as vectorized rolling columns on m5 (e.g. `bull_fvg_recent = (high.shift(2) < low).rolling(5).max()`), then test the column at the entry bar. Re-run the whole P.O.3 sweep afterward.

## 2. Critical: zero transaction costs — the edges don't survive them

No engine charges spread/commission/slippage on fills (P.O.3's `--spread` flag only widens the SL, and is off by default; CRT and H4-OB have nothing). Stops are tight M5 stops (P.O.3 median risk ≈ $5.25 on gold), so a 0.25 spread ≈ **0.05–0.06R cost per trade**. Recomputed from the trade logs:

| Strategy | Gross R | Net R (spread only) |
|---|---|---|
| P.O.3 XAUUSD (1,434 trades) | +39.3 | **−48.5** |
| CRT GBPUSD (2,177 trades) | −18.4 | **≈ −150** |
| H4 OB XAUUSD (+1.3R, cost ~0.04R × 66) | +1.3 | **negative** |

Any PF ≤ ~1.10 result here is noise once costs exist.

**Fix:** charge `spread + commission + slippage` on every entry and exit in all three engines, on by default. Then either widen stops (HTF-based stops lower cost-per-R) or accept fewer, larger trades.

## 3. Overfitting / hindsight in the "best configs"

- "bull-only" and "2024+" were chosen **after** seeing that gold went up. A live trader in 2022 couldn't have picked them.
- Best H4-OB config has **N=17 trades** — statistically meaningless.
- All sweeps are in-sample; the best row of a 23–27 setup sweep is expected to look good by chance.

**Fixes:**
- Replace hardcoded direction filters with a **causal regime filter** (e.g. daily close > SMA200 → longs only) so direction selection happens in real time.
- **Walk-forward validation**: optimize on 2022–2024, validate untouched on 2025–2026 (or rolling 12-month windows).
- Bootstrap the trade R series for significance; ignore configs with < ~100 trades.

## 4. P.O.3 profit is one year, not an edge

Yearly gross R: 2022 +0.4, 2023 +9.9, 2024 +1.5, **2025 +37.7**, 2026 −10.3. Net of costs, only 2025 is positive. As built, P.O.3 is a leveraged bet on gold's 2025 trend. Require positive expectancy in ≥3 of 4 years before trusting it.

## 5. CRT: the real signal is in natural RR — exploit it

Bucketing the 2,177 CRT trades by `natural_rr`:

| Natural RR | N | Gross R |
|---|---|---|
| ≤ 1.0 | 482 | −37.3 |
| 1.0–2.0 | 638 | −51.4 |
| **> 2.0** | **1,053** | **+70.3** |

`--min-rr 2.0` flips CRT from −18R to roughly +70R gross (still in-sample — validate out-of-sample and net of costs). Shallow re-entries near the opposite extreme are the losers; deep sweeps with room to run carry the entire edge.

## 6. H4 candle anchor mismatch

H4 bars are resampled at UTC 00/04/08/12/16/20. Brokers and TradingView anchor gold H4 to **NY 17:00** (UTC 21/22). Your OBs and CRT dealing ranges therefore don't match what an ICT trader sees live. Resample with the NY-17:00 offset (or test both anchors for robustness).

## 7. Execution realism

- Stops fill at exactly −1.0R: no gap/news slippage. Gold gaps through stops; add stop slippage (e.g. 0.1–0.3 × ATR or fill at next bar open beyond stop).
- Ambiguous bars (stop+target same M5 bar) resolve to stop — good and conservative — but consider M1 resolution for the 279 P.O.3 target exits to be sure.
- P.O.3 `max_hold` exits average **+0.83R over 195 trades** — the time stop is quietly profitable; test a trailing stop or structure-based exit instead of a fixed TP-or-SL.

## 8. Engineering

- **Rounding bug in trade logs:** CRT rounds prices to 3 dp — for GBPUSD this destroys risk distances (522/2,177 logged trades show entry == stop). Round FX to 5 dp.
- `iterrows()` over ~283k M5 bars is slow; vectorize state with numpy or numba — makes proper walk-forward sweeps feasible.
- One global `in_trade` flag means results are path-dependent (a trade blocks later signals). Also evaluate every signal independently to measure raw signal quality.
- No tests. Add unit tests for sweep/MSS/OB detection on tiny synthetic bars — would have caught the FVG bug.

## Priority order

1. Fix FVG bug + add costs to all engines → re-run everything (this resets the truth baseline).
2. Walk-forward split + causal regime filter to replace bull-only/2024+ hindsight.
3. Test CRT `min_rr ≥ 2` out-of-sample — most promising single improvement found.
4. NY-anchored H4 resample; stop slippage; rounding fix.
5. Explore P.O.3 time-stop/trailing exit (max_hold trades avg +0.83R).
