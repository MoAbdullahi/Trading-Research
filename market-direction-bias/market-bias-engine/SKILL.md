---
name: market-bias-engine
description: >-
  Compute a deterministic, transparent, multi-factor market bias (direction) of
  -1/0/+1 from OHLC price data, built on PyIndicators. Use this skill whenever
  the user wants the market direction, trend bias, or "which way is X leaning"
  for any instrument (stocks, crypto, forex, futures, indices); whenever they
  mention a bias engine, market structure / CHoCH / BOS, swing structure,
  SuperTrend, +DI/-DI or ADX regime, or premium/discount zones; whenever they
  want a per-bar bias column for a backtest or a current_bias() read to feed a
  TradePlan or entry decision; or whenever they hand over OHLC data (a CSV, a
  DataFrame, or a ticker symbol) and ask for the directional read with a
  factor-by-factor breakdown. Prefer this skill over ad-hoc indicator math any
  time the task is "what's the bias/direction here," so the answer comes out
  deterministic, weighted, regime-gated, and auditable rather than improvised.
---

# Market Bias Engine

A deterministic multi-factor engine that reads OHLC bars and returns a market
bias of **−1 / 0 / +1** plus a transparent, factor-by-factor account of why.
It is the deterministic bias layer meant to feed a `TradePlan`. Same bars in,
same bias out — no fitting, no randomness, no hidden state.

The engine code is bundled in `scripts/bias_engine/`. Use it; don't re-derive
the logic. Run everything from the `scripts/` directory so `import bias_engine`
resolves.

## How it works (one paragraph)

Five factors each cast a −1/0/+1 vote with an explicit, ablatable weight:
**structure / CHoCH-BOS (0.35, dominant)**, **swing structure (0.20)**,
**SuperTrend (0.15)**, **directional +DI/−DI (0.15)**, **premium/discount
(0.15)**. The weighted sum is the composite **score** in [−1, +1]. ADX is not a
factor but a **regime gate**: below `adx_ranging_threshold` (default 20) the
market is "ranging," so the score is halved and the neutral band widened — the
engine refuses to force a direction in chop. The gated score is thresholded
against the neutral band into the final bias.

## Setup

The only non-stdlib dependency beyond pandas/numpy is PyIndicators:

```bash
pip install pyindicators
```

## Input contract

A pandas DataFrame with at least `High`, `Low`, `Close` (an `Open` and `Volume`
are fine to include). It is feed-agnostic: whatever produced the bars — a direct
exchange feed, a normalized Level 1/2 provider, or a broker/API proxy
(TradingView, MT5) — once aggregated into an OHLC frame the engine treats them
identically. If indicator columns are already present, the engine won't
recompute them.

## Quickstart

```python
import sys; sys.path.insert(0, "scripts")     # or run from scripts/
from bias_engine import BiasEngine

result = BiasEngine().current_bias(ohlc_df)    # the call a TradePlan makes
print(result.breakdown_table())                # the "show your work" view

result.bias              # -1 / 0 / +1
result.label             # "bearish" / "neutral" / "bullish"
result.score             # raw weighted vote sum, [-1, +1]
result.effective_score   # after the regime gate
result.regime            # "trending" / "ranging"
result.components        # per-factor: vote, weight, contribution, reason
```

For a backtest or plotting, `BiasEngine().compute(ohlc_df)` returns the frame
with per-bar columns appended: `bias_vote_<factor>`, `bias_score`,
`bias_effective_score`, `bias_regime`, `bias`, `bias_label`.

## Getting data to run on

- **User provides a CSV or DataFrame** — use it directly (the validator
  auto-detects OHLC columns of any capitalization).
- **User names a ticker** — `scripts/validate_realdata.py` pulls via yfinance
  and prints the breakdown plus a 120-bar tally:

  ```bash
  cd scripts
  python validate_realdata.py SPY BTC-USD TSLA --period 2y
  python validate_realdata.py --csv path/to/bars.csv
  ```

  It also exposes tuning flags: `--pd-band`, `--adx-threshold`, `--invert-pd`,
  `--no-pd-regime`. If yfinance can't reach the network, fall back to a CSV;
  never try to route around a blocked fetch.

## Presenting results

Lead with the bias and conviction, then show `breakdown_table()` so the user
sees each factor's vote, weight, contribution, and reason. Call out the regime
(trending vs ranging) — a ranging-regime call is lower conviction by design.
When factors disagree (e.g. structure bullish but the trend factors bearish),
say so plainly; a neutral result there is the engine working, not failing.

## Configuration & ablation

All knobs live in `BiasConfig` / `FactorWeights` (see `scripts/bias_engine/
config.py`). To test whether a factor earns its weight, zero it and re-run:

```python
from bias_engine import BiasEngine, BiasConfig, FactorWeights
BiasEngine(BiasConfig(weights=FactorWeights(supertrend=0.0))).current_bias(df)
```

Key knobs: factor lengths, `adx_ranging_threshold` (20 permissive vs 25
textbook), `neutral_band` / `neutral_band_ranging`, `di_margin`,
`discount_is_bullish`, `pd_equilibrium_band`, `pd_regime_aware`,
`normalize_weights`. For what each factor reads, the exact PyIndicators column
encodings, and tuning guidance, read `references/factors.md`.

## A note on the premium/discount factor

Premium/discount is a **mean-reversion / location** read, not a trend read.
Under the Smart-Money sign a discount is a buy zone (+1) and a premium a sell
zone (−1) — but a strong uptrend lives in premium and a downtrend in discount,
so naively this factor *fights clean trends*. It is therefore **regime-aware by
default** (`pd_regime_aware=True`): it only votes in a ranging regime and
abstains in a trend. Consequence: in a trend the score tops out at ±0.85, with
conviction coming from the four structure/trend factors. This is intentional.

## Tests

```bash
cd scripts && python tests/test_bias_engine.py    # 11 deterministic tests
```

## Integrating with a TradePlan

```python
result = BiasEngine().current_bias(ohlc_df)
if result.bias != 0 and result.regime == "trending":
    side = "LONG" if result.bias > 0 else "SHORT"
    # hand `side` and `result.effective_score` (conviction) to the TradePlan
else:
    pass   # neutral or ranging -> stand aside, don't force an entry
```
