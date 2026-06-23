# Freqtrade Strategy Lab

A personal collection of [Freqtrade](https://www.freqtrade.io/) trading strategies and
backtest results, used to evaluate how different strategies perform on Bybit USDT pairs.

## Contents

| Path | Description |
|------|-------------|
| `strategies/` | Strategy implementations (see list below) |
| `config.json` | Freqtrade config (Bybit, USDT spot, 10,000 starting capital). API keys removed. |
| `compare.py` | Helper script for comparing backtest runs |
| `COMPARISON.md` | Side-by-side comparison of all strategies |
| `results/` | Saved per-strategy backtest reports |

## Strategies

- **NFI5MOHO_WIP**
- **ElliotV5_SMA_ninja**
- **ElliotV8_original_ichiv3**
- **ArcaneLiM2** - Ichimoku/DEMA + NFI-style multi-offset entries, trailing stop exits
- **NASOSv4**
- **NASOSv5_mod3**
- **StatisticalArbitrageStrategy** - requires live CoinGecko/Glassnode/LunarCrush data (not backtestable offline)
- **ElliotV5_Futures** - futures/leverage variant of ElliotV5_SMA_ninja (see FUTURES.md)

All strategies run on the `5m` timeframe.

## Results summary

Spot · 12 major pairs · 2025-02-01 → 2025-06-01 · 10,000 USDT start · market ~ -26%.

| Strategy | Total Profit | Win % | Sharpe | Max DD |
|----------|-------------:|:-----:|:------:|:------:|
| **NFI5MOHO_WIP** | **+10.14%** | 82.1% | 2.06 | 2.2% |
| ElliotV5_SMA_ninja | +5.45% | 81.8% | 0.92 | 2.3% |
| ElliotV8_original_ichiv3 | +5.12% | 76.0% | 1.04 | 4.1% |
| ArcaneLiM2 | +4.83% | 71.7% | 0.57 | 9.0% |
| NASOSv4 | +2.58% | 92.0% | 0.26 | 10.0% |
| NASOSv5_mod3 | -5.52% | 80.0% | -0.19 | 10.0% |

See **[COMPARISON.md](COMPARISON.md)** for the full table and notes.

## Spot vs Futures (leverage scaling)

A futures variant (`strategies/ElliotV5_Futures.py`) runs the ElliotV5 signals on
futures with configurable leverage. Summary across the leverage sweep:

| Level | Profit | Sharpe | Max DD |
|-------|-------:|:------:|:------:|
| Spot | +5.45% | 0.92 | 2.25% |
| Futures 1x | +5.90% | 1.00 | 2.20% |
| Futures 2x | +10.73% | 2.98 | 1.08% |
| Futures 5x | +17.07% | 1.24 | 6.30% |
| Futures 10x | +31.22% | 1.27 | 12.33% |

**Takeaway:** futures at 1x ≈ spot; leverage scales returns *and* drawdown
together (no real edge). The only structural edge — shorting the downtrend —
is untested because all strategies are long-only. Full analysis and caveats in
**[FUTURES.md](FUTURES.md)**.

## Running a backtest

```bash
freqtrade backtesting \
  --strategy NFI5MOHO_WIP \
  --config config.json \
  --timeframe 5m \
  --timerange 20250201- \
  --datadir user_data/data/bybit
```

Market data (`user_data/data/`) is **not** included to keep the repo lightweight.
Download candles with `freqtrade download-data` before backtesting.

## Notes

- Exchange: Bybit | Stake: USDT | Trading mode: spot
- API keys have been stripped from `config.json` - add your own before live/dry-run.
