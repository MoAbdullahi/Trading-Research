# Confluence Tester — Does Stacking ICT Rules Create an Edge?

The core ICT trading model is: read several rules, and when enough of them "agree"
on direction, enter. This tests that mechanically on XAUUSD M15 (2022–2026, 94,474 bars).
Four rules each vote −1/0/+1; every signal is a 2R trade (entry next-bar open, stop 1×ATR,
target 2×ATR, max hold 4h, 2bps slippage). With a 2R target, **breakeven needs a 33.3% win rate.**

The four rules: **A** liquidity sweep / turtle soup · **B** premium/discount mean-reversion ·
**C** FVG retrace (continuation) · **D** HTF trend (EMA-200).

## Results

| Signal | Trades | Win % | avg_R | Total R |
|---|---|---|---|---|
| A — sweep / turtle soup | 9,101 | 29.3% | −0.182 | −1,658 |
| B — premium/discount | 6,860 | 30.7% | −0.155 | −1,060 |
| C — FVG retrace | 20,624 | 30.2% | −0.165 | −3,400 |
| D — HTF trend (EMA-200) | 3,547 | 29.8% | −0.162 | −576 |
| **Confluence ≥2 agree** | 8,125 | 30.1% | −0.169 | −1,370 |
| **Confluence ≥3 agree** | 1,294 | 30.2% | −0.141 | −182 |
| Confluence ≥2 + NY kill zone | 1,254 | 29.9% | −0.112 | −140 |
| Confluence ≥2 + daily 12-month momentum | 4,302 | 31.8% | −0.124 | −534 |
| Confluence ≥2 + momentum + kill zone | 695 | 31.1% | −0.077 | −54 |

## What this proves

1. **Every rule is negative on its own** — win rates cluster at ~30%, below the 33.3% needed for a 2R trade. Each ICT rule, mechanically tested, is a slightly-losing coin flip on gold.

2. **Confluence does NOT create an edge.** Requiring 2 rules to agree gives −0.169R — *no better than the average single rule*. The win rate barely moves (30.1% → 30.2%). Requiring 3 to agree only trims the loss to −0.141R while collapsing the sample 7× (8,125 → 1,294 trades). **You cannot stack coin-flips into an edge.**

3. **Filters reduce losses, they don't manufacture edge.** Adding the New York kill-zone (−0.112) or aligning with the *genuinely profitable* daily 12-month momentum (−0.124), or both (−0.077), each makes it *less bad* — by being more selective and cutting the worst trades — but **none turns it positive.** Even borrowing our one proven edge can't rescue negative-edge entries.

4. **Why the win rate barely improves with agreement:** the rules are largely *correlated* (an order block, an FVG, and a "discount array" often mark the same candle). Stacking correlated signals adds *confidence* but almost no new *information* — which is exactly how traders talk themselves into bad trades with "five confluences."

## The lesson (this is the whole point)

> Confluence makes a setup *feel* stronger without making it *be* stronger. An edge has to come from at least one component that has a real, measured, standalone edge. Stacking rules that individually lose just gives you a smaller, more confident way to lose.

Contrast: the **12-month momentum basket** works (Sharpe 0.41, stable across regimes) because its underlying signal has genuine standalone edge. The intraday ICT rules don't — and no amount of confluence fixed that.

## Reproduce
`research_scripts/confluence_tester.py` (XAUUSD M15). Swap the rules or instrument to test your own confluence ideas — the method is the value: test each component alone first, then check whether stacking *raises expectancy* or merely *shrinks the sample*.
