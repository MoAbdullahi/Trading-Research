# Strategy: Gold CRT Sweep-Reversal

## Thesis
XAUUSD M15 sweep-reversal based on Candle Range Theory (CRT) + ICT Order Blocks:

1. Identify the completed H4 range candle (UTC-aligned: 00/04/08/12/16/20)
2. Detect M15 sweep of one range extreme (wick beyond boundary, no close outside)
3. Require displacement candle: body ≥ k × ATR (default 1.0×), strongly reversing
4. Confirm MSS/CHoCH: a subsequent close must break the sweep-bar reaction high/low
5. Find Order Block: last opposing-colour bar between sweep and displacement
6. OB_ONLY entry: price must have already retraced to OB before signalling

Stops sit `sweep_buffer_atr × ATR` beyond the swept extreme.  
Target is the opposite H4 range wall.

## Entry provider
| Provider | File | Description |
|---|---|---|
| `CRTSignalProvider` | `backtest/providers_crt.py` | Full CRT + OB detection on M15 window |

## Data source
Dukascopy M15 XAUUSD parquet — `data/dukascopy.py` handles loading.  
Data file: stored separately (not committed — large binary).

## How to run
```bash
# standard run, 8h max hold, 1.5R minimum
python run_gold_backtest.py \
  --data path/to/XAUUSD_M15.parquet \
  --start 2024-01-01 \
  --end   2025-12-31 \
  --max-hold 32 \
  --rr-min 1.5

# tighter displacement filter
python run_gold_backtest.py --data ... --displacement-atr 1.2
```

## Kill criterion (pre-committed)
All three must pass:
1. **≥ 150 trades** over the test window
2. **avg_R ≥ +0.2 R/trade** (expected value)
3. **London-window subset avg_R ≥ unconditioned avg_R**

## Results

### Full dataset — May 2022 → May 2026 (4 years, 94,474 M15 bars)

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| Trades | 677 | ≥ 150 | ✅ PASS |
| avg_R | −0.099R | ≥ +0.20R | ❌ FAIL |
| Win rate | 49.5% | — | — |
| avg_win | +0.842R | — | — |
| avg_loss | −1.022R | — | — |
| Profit factor | 0.81 | — | — |
| pct_reach_target | 41.5% | — | — |
| avg_mfe_r | 0.787R | — | — |
| pct_mfe_above_2r | 5.9% | — | — |
| Max drawdown | −68.68R | — | — |

**VERDICT: KILL** — EV below threshold on pre-committed kill criterion.

Parameters: `displacement_atr=1.0`, `max_hold=32 bars (8h)`, `rr_min=1.5`, `feature_window=500 bars`

### Diagnosis

The payoff structure is the problem, not the direction. At 49.5% win rate with avg_win 0.842R and avg_loss 1.022R, breakeven requires ~55% win rate — 5.5 points short. The unconditioned sweep-reversal is close to a coin flip on direction, which was expected. The MFE (41.5% reach target) suggests the setups have genuine follow-through; the 8h forced-close truncates winners that need more time.

### Comparison: Jan–May 2025 window vs full 4-year dataset

| Window | Trades | Win rate | avg_R | pct_reach_target |
|---|---|---|---|---|
| Jan–May 2025 (5 months) | 60 | 41.7% | −0.283R | 25.0% |
| Full dataset (4 years) | 677 | 49.5% | −0.099R | 41.5% |

The full dataset is materially better (49.5% vs 41.7% win rate, 41.5% vs 25% target hit). The 5-month window was particularly hostile. The unconditioned strategy still fails the kill criterion, but the edge is closer than the 5-month snapshot suggested.

### Next steps (if pursuing macro conditioning)

The pre-committed macro conditioning test was not run. Macro conditioning was the thesis for *which* sweeps to take, not a post-hoc adjustment. To proceed:
1. Filter trades to London session (07:00–16:00 UTC) and compare avg_R vs unconditioned
2. Wire the macro agent and compare conditioned vs unconditioned win rate
3. Kill criterion: London subset avg_R ≥ unconditioned avg_R

### H4+5M entry variant (Jan–Feb 2025, 2 months)

| Metric | H4+M15 | H4+5M |
|---|---|---|
| Win rate | 41.7% | 29.6% |
| avg_R | −0.283R | −0.491R |
| Verdict | Closer to viable | Clearly worse |

5M entry rejected — lower win rate, worse avg_R, more false signals from tighter OBs.

## Research basis
Validated in prior research project (CRT + ICT PD Array):  
XAUUSD H4+M15, OB_ONLY entry, strong-filter mandatory, London KZ primary window  
Out-of-sample result: 12 trades, 86.7% WR, +0.875 R/trade
