# Strategy: Equity ORB / VWAP Trigger

## Thesis
Regime-aware intraday entries on liquid US equities:
- **trend_up** (ORB breakout above high): LONG when price > VWAP + high RVOL + EMAs aligned
- **reversal** (ORB breakdown): fading extremes at support/resistance with oversold RSI
- **neutral**: flat (no trade)

## Entry providers
| Provider | File | Description |
|---|---|---|
| `DeterministicSignalProvider` | `backtest/providers.py` | Baseline regime rules as pure code |
| `PullbackSignalProvider` | `backtest/providers.py` | Fires only on pullbacks to VWAP/EMA within morning window |
| `LiveAgentSignalProvider` | `backtest/providers.py` | Calls real LLM agents (costs tokens) |

## Universe selection
`data/scanner.py` — `InPlayCriteria`: gap ≥ 3%, opening RVOL ≥ 2×, daily range ≥ $0.50  
`data/universe_liquid.txt` — 47 liquid non-mega-cap symbols

## How to run
```bash
# single symbol
python run_backtest.py --symbol AAPL --start 2025-01-01 --exit-mode full_target

# full rotating universe (5 months, scanner-filtered)
python run_universe_backtest.py --start 2025-01-01
```

## Verdict: DEAD

Pre-committed kill criterion: `pct_mfe_above_2r >= 33%`  
Result: **15.4%** across 91 trades / 30 symbols.  
Entries lack sufficient follow-through; thesis does not work on this data.

Ruled out in order:
1. Exit structure (breakeven park was destroying value) — fixed, still negative
2. Entry timing (pullback proximity) — made results worse
3. Universe selection (47 symbols, scanner-filtered) — did not rescue negative-edge entries
4. Entry follow-through (MFE analysis) — final kill signal
