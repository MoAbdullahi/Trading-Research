# Strategy Comparison — Spot

**Setup:** Bybit USDT spot · 5m timeframe · 12 major pairs
(BTC, ETH, SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, LTC, DOT, TRX)
**Period:** 2025-02-01 → 2025-06-01 · **Starting capital:** 10,000 USDT
**Market change over period:** ~ -26% (strong downtrend)

| Rank | Strategy | Total Profit | Final Balance | Trades | Win % | Profit Factor | Sharpe | Sortino | Max DD | Best Pair | Worst Pair |
|-----:|----------|-------------:|--------------:|:------:|:-----:|:-------------:|:------:|:-------:|:------:|-----------|------------|
| 1 | **NFI5MOHO_WIP** | **+10.14%** | 11,014.12 | 28 | 82.1% | 3.02 | 2.06 | 3.50 | 2.24% | ADA +16.38% | ETH -7.48% |
| 2 | ElliotV5_SMA_ninja | +5.45% | 10,544.95 | 11 | 81.8% | 3.35 | 0.92 | 0.77 | 2.25% | XRP +5.05% | BTC 0.00% |
| 3 | ElliotV8_original_ichiv3 | +5.12% | 10,511.64 | 25 | 76.0% | 1.97 | 1.04 | 0.91 | 4.14% | XRP +4.98% | BTC 0.00% |
| 4 | ArcaneLiM2 | +4.83% | 10,482.72 | 46 | 71.7% | 1.24 | 0.57 | 0.51 | 9.03% | XRP +16.64% | LINK -4.45% |
| 5 | NASOSv4 | +2.58% | 10,257.73 | 25 | 92.0% | 1.24 | 0.26 | n/a* | 10.02% | DOGE +8.03% | XRP -10.24% |
| 6 | NASOSv5_mod3 | -5.52% | 9,448.39 | 5 | 80.0% | 0.46 | -0.19 | -100 | 9.96% | XRP +7.94% | ADA -30.14% |
| — | StatisticalArbitrageStrategy | n/a | — | — | — | — | — | — | — | — | — |

\* NASOSv4 Sortino reported as an invalid extreme value by freqtrade (near-zero downside deviation).

## Notes

- **StatisticalArbitrageStrategy** could not be backtested: it pulls live data from
  CoinGecko, Glassnode, and LunarCrush APIs (the latter two require paid keys), so it
  cannot run on local historical data offline.
- **NFI5MOHO_WIP** was the clear winner — highest return (+10.14%) with the lowest
  drawdown (2.2%) and a strong Sharpe (2.06). It stayed net positive while the market
  fell ~26%.
- **NASOSv5_mod3** was the only loser (-5.52%), trading very rarely (5 trades) and
  getting caught badly on ADA (-30%).
- The Elliot variants traded selectively with high win rates and small drawdowns.
- High win rate alone is not enough: **NASOSv4** had the best win rate (92%) but only
  +2.58% return because its few losers were large.

## Reproduce

```bash
freqtrade backtesting \
  --strategy <NAME> --config config.json \
  --timeframe 5m --timerange 20250201- \
  --datadir user_data/data/bybit \
  --pairs BTC/USDT ETH/USDT SOL/USDT XRP/USDT BNB/USDT DOGE/USDT \
          ADA/USDT AVAX/USDT LINK/USDT LTC/USDT DOT/USDT TRX/USDT
```

Full per-strategy reports are in [`results/`](results/).
