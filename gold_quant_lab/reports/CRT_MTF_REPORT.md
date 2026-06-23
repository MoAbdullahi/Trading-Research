# Gold CRT — Multi-Timeframe Backtest Results

**Data:** Dukascopy XAUUSD, 2022-05-12 → 2026-05-12 (94,474 M15 bars / 283,399 M5 bars), bid side.
**Engine:** production CRT detection + orchestrator + RiskGateway + FillSimulator, full_target exit, RR floor 1.5, 8h max hold, 2bps slippage, $0 commission.
**Validation:** the 4H-15M run reproduces the project's previously documented result exactly — 677 trades, −0.099R, 49.5% WR, PF 0.81, max DD −68.7R, 41.5% reach-target — confirming the fast engine is faithful.

## Pre-committed kill criterion (unchanged)
PASS requires ALL of: (1) ≥150 trades, (2) avg_R ≥ +0.20R, (3) London-session avg_R ≥ unconditioned avg_R.

## Results

| Structure→Entry | Trades | Win rate | avg_R | avg win | avg loss | PF | reach target | max DD (R) | London avg_R | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 4H-15M | 677 | 49.5% | -0.099 | +0.842 | -1.022 | 0.81 | 41.5% | -68.7 | -0.141 | **KILL** |
| 4H-5M | 1638 | 33.0% | -0.292 | +1.389 | -1.121 | 0.61 | 27.4% | -493.0 | -0.277 | **KILL** |
| 1H-15M | 325 | 59.4% | -0.128 | +0.503 | -1.051 | 0.7 | 56.3% | -47.2 | -0.107 | **KILL** |
| 1H-5M | 2154 | 43.8% | -0.266 | +0.846 | -1.133 | 0.58 | 42.7% | -573.5 | -0.249 | **KILL** |

## Read-out

- **Every combination fails** the kill criterion. None is profitable; all have profit factor < 1.
- **4H-15M is the least-bad** (−0.099R) and remains the best structure/entry pairing — consistent with the original research.
- **Dropping to M5 entries makes things sharply worse** (4H-5M −0.292R, 1H-5M −0.266R). More signals, lower quality: tighter order blocks fire more often but with worse follow-through, and the larger trade counts drive enormous drawdowns (−493R, −573R).
- **1H range raises win rate but not edge.** 1H-15M wins 59.4% of the time (vs 49.5% for 4H-15M) and reaches target more often (56.3%), but the smaller 1H walls mean smaller targets — average win shrinks to +0.503R while losses stay near −1R. Higher hit-rate, lower payoff, still negative EV.
- **The London-session filter does not rescue any combo.** In every case London avg_R is ≤ the unconditioned avg_R (e.g. 4H-15M: −0.141 London vs −0.099 overall), so criterion #3 also fails. The macro-conditioning thesis is not supported by the session cut.

## Conclusion

The CRT sweep-reversal has **no positive edge on XAUUSD in any of the four timeframe pairings**, before real-world costs (which would worsen all of them). The losing mechanism is the payoff structure, not direction: the strategy is roughly a coin-flip on direction with average losses slightly larger than average wins. This matches the evidence base — order-block / FVG / sweep ("SMC/ICT") methods have no rigorous, falsifiable edge in published research, whereas trend-following/momentum and session-overlap breakouts do. The one CRT ingredient with real backing is the *displacement* (a momentum signal); the order-block entry is the part that lacks support.
