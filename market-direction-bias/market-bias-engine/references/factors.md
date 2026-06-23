# Factor reference

What each factor reads, the exact PyIndicators column it depends on, how that
column is encoded, and how to tune it. Read this when you need to explain a
vote, debug an unexpected reading, or adjust the engine.

## The five factors

| Factor | Weight | PyIndicators call | Column read | Encoding |
|---|---|---|---|---|
| structure | 0.35 | `market_structure_choch_bos(length=structure_length)` | `market_trend` | −1 / 0 / +1 |
| swing | 0.20 | `swing_structure(swing_length=swing_length)` | `swing_direction` | −1 / 0 / +1 (with `swing_structure` label HH/HL/LH/LL) |
| supertrend | 0.15 | `supertrend(atr_length, factor)` | `supertrend_trend` | 1 = bull, 0 = bear |
| directional | 0.15 | `adx(period=adx_period)` | `+DI`, `-DI` | numeric; vote = sign(+DI − −DI) with `di_margin` deadband |
| premium_discount | 0.15 | `premium_discount_zones(swing_length=pdz_swing_length)` | `pdz_zone`, `pdz_zone_pct` | zone in {premium, discount, equilibrium, ''}; pct = depth into zone (0=equilibrium, 100=extreme) |

The default weights sum to **1.0**, so the raw composite score is bounded in
[−1, +1] and each weight reads as the max share of the vote a factor can swing.

## Vote semantics

- **structure** — reads direction from `market_trend` (itself derived from
  CHoCH on reversal and BOS on continuation). The breakdown surfaces the most
  recent CHoCH/BOS event so the *reason* for the trend is visible. Dominant by
  design: structure is the primary read on where price is trying to go.
- **swing** — HH/HL sequence → +1, LH/LL → −1, mixed → 0. The label (e.g. "HH")
  is shown as evidence.
- **supertrend** — ATR trailing stop: price above the line → +1, below → −1.
- **directional** — +DI vs −DI. Abstains (0) when the two are within
  `di_margin` of each other, so balanced directional movement isn't forced into
  a side.
- **premium_discount** — location within the dealing range. Default Smart-Money
  sign: discount (lower half) → +1, premium (upper half) → −1. See the regime
  and deadband notes below.

## The ADX regime gate

ADX is a gate on conviction, not a factor. When `ADX < adx_ranging_threshold`
(default 20) the regime is **ranging**: the composite score is multiplied by
`ranging_score_multiplier` (default 0.5) and the neutral band widens from
`neutral_band` (0.10) to `neutral_band_ranging` (0.30). The final bias is the
gated score thresholded against the active band: `> band` bullish, `< −band`
bearish, else neutral.

Tuning ADX: 20 is permissive (more bars count as "trending"); 25 is Wilder's
textbook trend threshold (stricter, more bars treated as ranging). Raise it if
you see choppy names being called trending.

## Premium/discount: depth, deadband, regime-awareness

- `pdz_zone_pct` is **depth into the zone**, NOT absolute range position:
  0 = at equilibrium, 100 = at the range extreme. So "premium, 17% into zone"
  means price is only just above fair value.
- `pd_equilibrium_band` (default 0): if depth is below this, the factor abstains
  — it's too close to fair value to give a real location read. Try 10–15 to
  suppress near-equilibrium votes.
- `pd_regime_aware` (default **True**): location is mean-reversion logic, which
  only applies in a range. In a trend it fights the move (uptrend → premium →
  bearish vote; downtrend → discount → bullish vote), so when True the factor
  votes only in a ranging regime and abstains in a trend. Set False for the
  literal spec (vote in every regime).
- `discount_is_bullish` (default True): the SMC sign. Set False to read "holding
  in premium" as raw strength instead (premium → +1, discount → −1).

## Ablation

To check whether a factor earns its weight, set it to 0 and compare scores:

```python
from bias_engine import BiasEngine, BiasConfig, FactorWeights
full = BiasEngine().current_bias(df).score
ablated = BiasEngine(BiasConfig(weights=FactorWeights(swing=0.0))).current_bias(df).score
```

Set `normalize_weights=True` to renormalise the surviving weights back to 1.0
for a like-for-like comparison (otherwise the score range just shrinks, which is
also a valid, more literal reading).

## Warm-up / missing data

Every factor abstains (votes 0) when its indicator column is NaN or empty rather
than guessing, so early bars degrade gracefully instead of producing spurious
high-conviction reads.

## Empirical behaviour (validated)

On a synthetic regime-switching series (bull → range → bear) the engine reads
~92% bullish through the bull leg, flags ~76% of the range as ranging and goes
mostly neutral, then ~98% bearish through the bear leg. On real symbols
(equities, metals, crypto; daily and hourly) the regime-aware premium/discount
factor correctly mutes in clean trends (e.g. a gold downtrend where it would
otherwise vote contrarian-bullish) while keeping its vote in ranging names.
