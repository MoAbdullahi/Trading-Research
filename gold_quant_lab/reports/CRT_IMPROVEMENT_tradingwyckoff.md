# Can tradingwyckoff.com's CRT improve our strategy? — Tested

Source: https://tradingwyckoff.com/en/crt/ (Rubén Villahermosa). A high-quality, honest CRT guide.

## What the article says (and how it lines up with our results)

- **CRT = Wyckoff Spring/Upthrust on one candle.** Sweep a prior candle's extreme → re-enter the range → target the opposite extreme. (This is exactly our engine.)
- **Its honest win-rate table is the key:** Raw CRT **45–50% (coin-flip)** → +HTF trend 50–58% → +Wyckoff phase 55–62% → +trend+killzone+key level 60–65%. It states plainly: *"Raw CRT without context is closer to a coin flip."*
- That **confirms our finding**: our unconditioned CRT was −0.099R, a coin flip. The article agrees raw CRT has no edge.
- Its one *profitable* system ("Wyckoff Spring Gold," PF>1.5 over 20yr) is **bullish-only, H4/D1, trend/accumulation context** — i.e. buying dips in an uptrend = the trend-following we already validated on gold.

## The testable improvement: daily-bias filter

The article's #1 recommendation is to **only take CRT setups aligned with the higher-timeframe daily bias**. We added that to our CRT engine on gold M15:

| CRT variant | Trades | Win% | avg_R | PF |
|---|---|---|---|---|
| Baseline (no filter) | 304 | 35.9% | −0.119 | 0.83 |
| **+ daily EMA-50 trend** | 125 | 38.4% | **−0.047** | 0.93 |
| **+ daily 12-month momentum** | 133 | 39.1% | **−0.016** | 0.98 |
| + trend + killzone (London/NY open) | 48 | 29.2% | −0.187 | 0.76 |
| + killzone only | 125 | 28.8% | −0.234 | 0.70 |

*(RR checked on actual fill → stricter than our earlier runner; baseline 304/−0.119R vs the looser 677/−0.099R. Same engine across all rows.)*

## What we learned

1. **The daily-bias filter genuinely helps** — it cuts the loss from −0.119R to ~−0.016R (essentially breakeven), and lifts win rate and profit factor toward 1.0. This validates the article's core claim and is the single best CRT improvement found.
2. **But it does not make CRT profitable** — it moves it from "clearly losing" to "breakeven before costs," not to the +0.20R bar. After real spread/commission it would still be slightly negative.
3. **The killzone filter HURT on gold** (−0.187 / −0.234), the opposite of the article's claim. The article is FX/indices-centric; gold's range is NY-driven, and we'd already found session filters don't rescue gold CRT. So this recommendation does **not** transfer to gold.
4. **The deeper point:** as you add the trend filter, CRT converges toward "trade with the daily trend" — i.e. trend-following. The improvement comes *from the trend component, not the sweep/OB mechanics.* The article inadvertently proves the same thing our whole project did: the durable edge is trend/momentum; CRT is a (worse) wrapper around it.

## Recommendation

- **Adopt the daily-bias filter** if you keep trading CRT — it's a real, free improvement and halves-to-eliminates the bleed.
- **Drop the killzone filter for gold** (it backfires).
- **But the honest conclusion stands:** filtered CRT is ~breakeven, while the daily trend/momentum it leans on is itself the profitable strategy (gold daily trend PF 2–3.7; 12-month momentum basket Sharpe 0.4–0.6). If the trend filter is what makes CRT work, trade the trend directly — it's simpler and has the measured edge.
