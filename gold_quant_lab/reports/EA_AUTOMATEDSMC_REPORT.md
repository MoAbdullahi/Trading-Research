# automatedSMC v2.30 EA — What It Does & Whether It Has an Edge

## What the EA does (plain English)

A fully automated Smart-Money-Concepts bot. HTF = M15, LTF = M1.

1. **Finds structure.** Forward-confirmed swing highs/lows (length 20) on M15. When price *closes* beyond a swing → Break of Structure (continuation) or Change of Character (reversal). That arms a trade in the break direction.
2. **Picks an order block.** The strongest opposing-body candle in the last 10 bars becomes the entry zone. Stop = OB edge − 0.5×ATR; take-profit = a fixed 2R from the OB.
3. **Demands confluence (≥5 of 8).** Structure bias, premium/discount, liquidity pool, liquidity sweep, price-at-OB (+volume strength), LTF change-of-character (M1), volume-profile POC, and FVG alignment.
4. **Filters by time/regime.** Only fires in London (07–09 UTC) or NY (13–15 UTC) kill zones, and only when ADX(14) ≥ 22.
5. **Manages the trade.** 1% risk, breakeven at 0.5R, partials at 1R/2R/3R, swing trailing stop, 3% daily loss limit.
6. **Five "fixes" over v2.10:** a min-RR gate (1.2), an OB-edge gate (enter only in the outer 40% of the OB), a same-OB re-entry block, and added close-logging/dead-position handling.

## Does it have an edge? Test result (re-encoded core, XAUUSD M15, 2022–2026)

| Configuration | Trades | Win % | avg_R | Profit factor |
|---|---|---|---|---|
| Full gating (kill zone + ADX + all conditions) | 170 | 37.6% | **−0.383** | 0.66 |
| No kill-zone / ADX gate | 487 | 23.8% | −0.345 | 0.69 |
| Same engine on GBPUSD | 161 | 31.7% | −0.947 | 0.26 |

**No edge.** The full-gating run loses −0.38R per trade (profit factor 0.66). Fidelity check: my re-encoding fired **170 trades** vs the EA's own cited **168** — essentially identical, so this is a faithful test, not a strawman.

Why it loses even at 37.6% win rate: exactly the pathology the EA's own diagnostic flagged — entries land late inside the order block (the report said ~81% of the way to TP), so winners book tiny fractional-R gains while losers take the full stop. Asymmetric payoff → negative expectancy.

## Red flags visible in the code itself

- **It's a patched strategy, not a discovered edge.** Five "fixes" bolted onto a losing v2.10, with thresholds *loosened to keep trades* — the comments literally say "report said 1.5, tested too tight → 1.2" and "report said 10% → 40%." That is calibrating to the backtest (overfitting), not finding signal.
- **Two-to-three of the eight conditions are admitted freebies** — the author notes C3 (liquidity pool) and C4 (sweep) "pass 100% of the time," so "8-condition confluence" is really ~5, and we already proved stacking these conditions doesn't create edge.
- **Same family, same result.** This is structure-break → order-block reversal — the identical mechanism as the CRT strategy (−0.10R) and the confluence test (−0.15R). More filters didn't fix it; they just shrank the sample.

## Bottom line

A sophisticated, well-engineered piece of software wrapped around a **negative-expectancy entry**. The engineering (risk caps, partials, logging) is sound; the *edge* isn't there. Consistent with everything else tested: the SMC/ICT order-block family has no measurable edge on gold, while daily trend-following and the 12-month momentum basket do.

*Re-encoding approximations: LTF CHoCH uses M15 internal-5 (EA uses M1, unavailable); C3/C4/C7 granted per the author's "always-pass" note. Exit modelled as TP/SL only (partials reduce variance, not expectancy). Research, not financial advice.*
