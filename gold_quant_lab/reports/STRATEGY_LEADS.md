# Strategy Leads — Reddit / Open-Source GitHub (assessed)

Found via web search and triaged with the same lens as the rest of this project:
"promising" = testable code with some validation, not hype. **GitHub is reachable
from the research environment, so any of these can be cloned and re-tested on your
gold/FX data with our kill-criteria + walk-forward harness.**

## Group A — ICT / SMC family (what you asked for: "like CRT + ICT PD Array")

| Repo | What it is | Honest take |
|---|---|---|
| `joshyattridge/smart-money-concepts` | The canonical Python SMC **indicator library** — OB, FVG, BOS/CHoCH, liquidity, swings. (The automatedSMC EA's FVG definition came from here.) | Best-built of the group. It's a *toolkit*, not a strategy. Useful for cleanly encoding SMC rules — but our tests show those signals lack edge. |
| `starckyang/smc_quant` | SMC strategy on ETHUSDT (OB/FVG/BOS) with backtesting.py | A concrete SMC strategy we can backtest directly. Expect to confirm the no-edge pattern; worth a quick run. |
| `jmlacasa/backtesting_finance` | Multi-timeframe order-block strategy (backtesting.py) | Same family, multi-TF. Testable. |
| `smtlab/smartmoneyconcepts`, `tsunafire/PineScript-SMC-Strategy` | More SMC indicator/Pine implementations | Variants; low priority. |

**Bottom line for Group A:** these are the same OB/FVG/sweep mechanics we've now shown have no measurable edge (CRT −0.10R, confluence −0.15R, the EA −0.38R). Worth cloning `joshyattridge` as a clean indicator toolkit; expect the strategy repos to confirm the negative.

## Group B — Evidence-backed family (more likely to actually have edge)

| Repo | What it is | Why promising |
|---|---|---|
| **`noterminusgit/statarb`** | Production-grade statistical arbitrage: 20+ alphas, PCA decomposition, Barra risk model, **realistic transaction-cost modeling**, ~1,400 US equities, daily rebalance | The most serious repo found. Proper risk + cost modeling is exactly what separates real edges from backtest fantasy. High priority. |
| **`wangzhe3224/awesome-systematic-trading`** | Curated master list of systematic-trading strategies, libraries, papers (crypto/stocks/futures/FX) | Best *index* to mine for vetted, paper-backed strategies. Start here for breadth. |
| `IsaacCheng9/quant-trading-strategy-backtester` | Backtester with **walk-forward validation, transaction costs + slippage**; mean-reversion, MA-crossover, pairs | Sound methodology (the discipline matters more than the strategies). |
| `chase-keskinyan/momentum-reversal-crypto` | Interpretable momentum/reversal signals on BTC + alts, institutional-stat-arb inspired | Momentum/reversal — the family that actually validated in our work. |
| `adamd1985/quant_research` | Momentum & mean-reversion research notebook | Quick reference implementation. |

**Bottom line for Group B:** these line up with what *did* validate here (trend/momentum, and now stat-arb/mean-reversion as new candidates). `noterminusgit/statarb` and the momentum repos are the ones I'd actually test.

## A Reddit reality-check (r/algotrading consensus)

The recurring community consensus is worth stating plainly: the durable edges people actually report are **momentum/trend, mean-reversion, and stat-arb / pairs** — the same families with academic backing. ICT/SMC is enormously popular in content but **almost never** appears in the "here's my live-verified edge" threads. That matches our results exactly.

## Recommended next action

1. **Clone + backtest `noterminusgit/statarb`** logic on a liquid equity/ETF set (or adapt its pairs/mean-reversion alphas to your FX/metals basket) with our cost + walk-forward discipline.
2. **Clone `starckyang/smc_quant`** and run it as-is — a fast, fair confirmation of whether *anyone's* packaged SMC strategy survives our kill criteria (prediction: it won't).
3. Harvest `joshyattridge/smart-money-concepts` as a clean indicator library if we want to keep probing SMC variants.

Tell me which to pull first and I'll clone it and run it on your data.
