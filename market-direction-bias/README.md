# bias_engine

A deterministic, transparent, **multi-factor market-direction engine** built on
[PyIndicators](https://github.com/coding-kitties/PyIndicators). It reads a
plain OHLC time-series and returns a market bias of **−1 / 0 / +1**, along with
a component-by-component account of *why*. It is meant to drop in as the
deterministic bias layer feeding a `TradePlan`.

Same bars in, same bias out — no fitting, no randomness, no hidden state. That
is the entire point: the layer a trade decision leans on should be auditable.

## How it works

Five factors each cast a **−1 / 0 / +1 vote**, each with an explicit, ablatable
weight. The composite **score** is the weighted sum of votes, so it lives in
`[−1, +1]`:

| Factor | Weight | Source (PyIndicators) | Reads |
|---|---|---|---|
| **Structure (CHoCH/BOS)** | **0.35** | `market_structure_choch_bos` → `market_trend` | dominant: where structure says price is going |
| **Swing structure** | 0.20 | `swing_structure` → `swing_direction` | HH/HL (bull) vs LH/LL (bear) |
| **SuperTrend** | 0.15 | `supertrend` → `supertrend_trend` | ATR trailing-stop trend |
| **Directional (+DI/−DI)** | 0.15 | `adx` → `+DI`, `-DI` | which directional movement dominates |
| **Premium/Discount** | 0.15 | `premium_discount_zones` → `pdz_zone` | location in the dealing range |

The weights sum to **1.0**, so each weight reads directly as the maximum share
of the vote a factor can swing.

### The ADX regime gate

ADX is not a factor — it is a **gate on conviction**. When ADX is below
`adx_ranging_threshold` (default 20), the market is treated as *ranging*, and
the engine does two things:

1. **Halves** the composite score (weak confluence can't masquerade as conviction), and
2. **Widens** the neutral band (default `±0.10` → `±0.30`).

Together these make the engine **refuse to force a direction in chop**. The
final bias is the gated ("effective") score thresholded against the neutral
band.

### A note on Premium/Discount sign

Premium/discount is a **mean-reversion / location** read, not a trend read. By
Smart-Money convention a **discount** (lower half of the range) is where you
want to *buy* (+1) and a **premium** (upper half) is where you want to *sell*
(−1). The catch: a strong uptrend lives in premium and a strong downtrend lives
in discount, so summed naively into a directional score this factor *fights
clean trends*.

To handle that, the factor is **regime-aware by default**
(`pd_regime_aware=True`): it only votes in a **ranging** regime — where
mean-reversion actually applies — and **abstains in a trend**, so it never
drags against an established move. (Consequence: in a trending regime the score
tops out at ±0.85, since this factor sits out; conviction there comes from the
four structure/trend factors.) Set `pd_regime_aware=False` to let it vote in
every regime (the literal spec). The sign itself is also configurable:
`discount_is_bullish=False` reads "holding in premium" as raw strength instead.

## Usage

```python
from bias_engine import BiasEngine
import pandas as pd

ohlc = pd.DataFrame(...)            # columns: High, Low, Close (+ Open, Volume)

engine = BiasEngine()              # defaults match the spec
result = engine.current_bias(ohlc) # the call a TradePlan makes

result.bias              # -1 / 0 / +1
result.label             # "bearish" / "neutral" / "bullish"
result.score             # raw weighted vote sum, [-1, +1]
result.effective_score   # after the regime gate
result.regime            # "trending" / "ranging"
result.components        # per-factor vote, weight, contribution, reason
print(result.breakdown_table())    # the "show your work" view
```

For backtests or plotting, `engine.compute(ohlc)` returns the input frame with
per-bar columns appended: `bias_vote_<factor>`, `bias_score`,
`bias_effective_score`, `bias_regime`, `bias`, `bias_label`.

### Feeding it data

The engine ingests a **normalized OHLC time-series** (a pandas DataFrame with
at least `High`, `Low`, `Close`). It is deliberately feed-agnostic: whether the
bars come from a direct exchange feed, a normalized Level 1/2 provider, or a
broker API proxy (TradingView / MT5), once they are aggregated into a TSDB-style
frame the engine treats them identically. If indicator columns are already
present it won't recompute them.

### Wiring into a TradePlan

```python
result = engine.current_bias(ohlc)
if result.bias != 0 and result.regime == "trending":
    side = "LONG" if result.bias > 0 else "SHORT"
    # hand `side` + `result.effective_score` (conviction) to the TradePlan
else:
    pass  # neutral or ranging -> stand aside, don't force an entry
```

## Configuration & ablation

Everything lives in `BiasConfig` / `FactorWeights` (see `config.py`). To test
whether a factor earns its weight, zero it out and re-run:

```python
from bias_engine import BiasEngine, BiasConfig, FactorWeights

cfg = BiasConfig(weights=FactorWeights(supertrend=0.0))
BiasEngine(cfg).current_bias(ohlc)        # score shifts by SuperTrend's old contribution
```

Set `normalize_weights=True` to renormalise the survivors back to 1.0 for a
like-for-like comparison. Other knobs: factor lengths, `adx_ranging_threshold`,
`ranging_score_multiplier`, `neutral_band` / `neutral_band_ranging`,
`di_margin`, `discount_is_bullish`.

`pd_equilibrium_band` (default 0) controls how deep into a premium/discount
zone price must be before that factor votes. PyIndicators' `pdz_zone_pct` is
*depth into the zone* (0 = at equilibrium, 100 = at the range extreme), so a
bar reading "premium, 17% into zone" is barely above fair value. With the band
at 0 it still votes; set it to ~10-15 and the factor abstains near equilibrium,
only speaking when price is meaningfully into a zone.

## Layout

```
bias_engine/
  __init__.py     public API
  config.py       BiasConfig, FactorWeights (all knobs)
  factors.py      the five -1/0/+1 vote functions (pure, testable)
  engine.py       BiasEngine, BiasResult, Component
tests/
  test_bias_engine.py   synthetic up/down/range fixtures (10 tests)
example_usage.py        self-contained demo (no network)
validate_realdata.py    eyeball check on live tickers (yfinance) or a CSV
```

## Validation

`tests/test_bias_engine.py` asserts behaviour on hand-built fixtures where the
right answer is known (clean uptrend → bullish, downtrend → bearish, white-noise
range → ranging regime engages). On a synthetic regime-switching series
(bull → range → bear) the engine reads **92% bullish** through the bull leg,
flags **76% of the range as ranging** and goes mostly neutral, then **98%
bearish** through the bear leg.

Run the tests:

```bash
python tests/test_bias_engine.py      # or: pytest -q
```

Real-data sanity check (run where Yahoo Finance is reachable):

```bash
pip install yfinance
python validate_realdata.py SPY BTC-USD TSLA
# or
python validate_realdata.py --csv my_bars.csv
```

## Requirements

- Python 3.10+
- `pyindicators` (`pip install pyindicators`)
- `pandas`, `numpy`
- `yfinance` only for `validate_realdata.py`

## Disclaimer

For research and educational use. This is a deterministic signal-processing
layer, not financial advice; it does not place trades. Markets involve real risk
of loss — validate thoroughly before relying on any output.
