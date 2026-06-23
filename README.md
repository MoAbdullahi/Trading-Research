# Trading Research

A consolidated repository of systematic trading strategy research across gold, forex, and equities. All work is built on tick-accurate historical data, pre-committed kill criteria, and walk-forward validation — the goal is measured, out-of-sample-positive expectancy, not concepts that look good in hindsight.

---

## Projects

| Folder | What it is | Status |
|--------|-----------|--------|
| [trading-system](./trading-system/) | Production-grade multi-agent trading system using LangGraph — LLM agents plan, deterministic Python executes and risks | Active research scaffold |
| [GOLD_CRT_ICT_PD_Array_Strategy](./GOLD_CRT_ICT_PD_Array_Strategy/) | Python backtesting suite for CRT, ICT H4 OB, and ICT P.O.3 strategies on XAUUSD and GBPUSD (4 years, tick-accurate Dukascopy data) | Backtested |
| [ICT-MultiTF-Strategy-Research](./ICT-MultiTF-Strategy-Research/) | Systematic 240-combination parameter sweep of ICT multi-timeframe strategy across 6 instruments — Python engine + MT5 EA + interactive Dash dashboard | Validated (walk-forward pass) |
| [fable5-improved-strategy](./fable5-improved-strategy/) | Fixed and extended v2 engines for CRT, P.O.3, and ICT OB — bugs patched, transaction costs added, walk-forward split enforced | Backtested |
| [TimesFM](./TimesFM/) | Experiment wiring Google's TimesFM 2.5 foundation model as an H4 direction filter, with M15 rejected-level entries | Experimental |
| [gold_quant_lab](./gold_quant_lab/) | Broader research lab testing ICT/CRT concepts, trend-following, and cross-sectional momentum on a 15-instrument basket | Research |
| [freqtrade-strategies](./freqtrade-strategies/) | Freqtrade crypto strategy collection tested on Bybit USDT pairs — includes NFI, ElliotV5, NASOS, ArcaneLiM2, and a futures leverage sweep | Backtested |

---

## Key Findings Across All Projects

### What has a measurable edge

| Strategy | Finding | Source |
|----------|---------|--------|
| ICT H4-M5 OB + MSS confirmation | +992R over 4 years, 75% WR, Calmar 140, strong walk-forward pass (99.5% metric retention OOS) | `ICT-MultiTF-Strategy-Research` |
| Daily trend-following on XAUUSD (Donchian / EMA cross) | avg_R +0.27–0.58, PF 1.8–3.7, survives out-of-sample | `gold_quant_lab` |
| 12-month cross-sectional momentum (15-instrument basket) | L/S Sharpe 0.56, stable across two independent 6-year regimes | `gold_quant_lab` |
| NFI5MOHO_WIP (crypto, Freqtrade) | +10.14% over 4 months in a -26% market, Sharpe 2.06, max DD 2.2% | `freqtrade-strategies` |

### What doesn't hold up

| Claim | Finding | Source |
|-------|---------|--------|
| ICT risk entries (no MSS confirmation) | Negative expectancy in every configuration tested across 240 combos | `ICT-MultiTF-Strategy-Research` |
| CRT on GBPUSD M5 | Unviable — spread alone eats 0.20–0.23R per trade on M5 stops | `fable5-improved-strategy` |
| ICT confluence (stacking ≥2–3 rules) | Each rule −0.15 to −0.18R; stacking to ≥3 rules still −0.14R | `gold_quant_lab` |
| ICT/CRT sweep-reversal methods at any timeframe | avg_R −0.10 to −0.29, PF 0.58–0.81 | `gold_quant_lab` |
| Gold CRT sweep-reversal (live system) | avg_R −0.099R over 677 trades, 4 years → kill criterion triggered | `trading-system` |

### The cross-cutting lesson

> **Entry style matters more than entry filters.** Confirmation (MSS) entry completely dominates risk entry — avg Total R +415 vs −539. With M5 stops, spread alone eats 5–25% of risk per trade. The biggest lever is larger risk distances (higher-TF entries, structural stops), not more filters.

---

## Repo Structure

```
Trading-Research/
├── trading-system/                  Multi-agent live trading scaffold (LangGraph + LLMs)
├── GOLD_CRT_ICT_PD_Array_Strategy/  CRT / ICT H4 OB / P.O.3 backtest suite
├── ICT-MultiTF-Strategy-Research/   240-combo parameter sweep + MT5 EA + dashboard
├── fable5-improved-strategy/        v2 engines with cost model + walk-forward
├── TimesFM/                         TimesFM 2.5 H4 direction filter experiment
├── gold_quant_lab/                  Trend-following + momentum research lab
└── freqtrade-strategies/            Crypto strategy collection (Bybit / Freqtrade)
```

---

## Common Data Format

Most backtests share a common parquet layout:

```
data/
├── m5/    <SYMBOL>_M5.parquet     (5-minute bars, Dukascopy)
├── m15/   <SYMBOL>_M15.parquet    (15-minute bars)
├── h4/    <SYMBOL>_H4.parquet     (4-hour bars, NY 17:00-anchored)
└── daily/ <SYMBOL>_D1.parquet     (daily bars)
```

Symbols used: `XAUUSD`, `GBPUSD`, `EURUSD`, `USDJPY`, `NAS100`, `US30`. Data is not included in the repo — see individual folder READMEs for fetch instructions.

---

## Disclaimer

All work here is for research and educational purposes only. Past backtest performance does not guarantee future results. Nothing in this repository constitutes financial advice.
