# TimesFM Direction + LTF Rejection-Entry Test

A self-contained experiment that bolts onto the existing v2 suite. The hypothesis
you described:

> Use **TimesFM** ([google-research/timesfm](https://github.com/google-research/timesfm))
> to read **market direction on the higher timeframe (H4)**. When a trend is
> established, **time the entry on a lower timeframe (M15)** using levels the price
> has **already visited and rejected**.

This folder implements that as two decoupled layers — *direction* (H4) and
*entry* (M15) — so each can be swapped or tuned independently, and runs them
through the same cost model and walk-forward split as the rest of the project.

## How it works

**1. Direction (H4) — `direction_model.py`**
A forecaster looks at a trailing window of H4 closes and predicts the next
`horizon` closes with quantiles, then collapses that to a per-bar bias:

| signal | meaning | rule ("median forecast + quantile gate") |
|---|---|---|
| `+1` | bullish | median forecast clears `close × (1+min_move)` **and** the low quantile is still above the current close |
| `-1` | bearish | mirror image with the high quantile below the current close |
| `0`  | no trade | the forecast band straddles the current price (low confidence) |

The gate is the point of using a *quantile* model: we only take a side when even
the conservative quantile agrees, which filters weak/uncertain forecasts.

Two interchangeable forecasters, same interface:
- **`TimesFMForecaster`** — the real Google TimesFM 2.5 (200M) model.
- **`BaselineForecaster`** — a dependency-free drift+quantile model so the entire
  pipeline runs and is testable without the foundation model. *Not predictive —
  it exists to exercise the plumbing.*

**2. Entry levels (M15) — `levels.py`**
"Visited-and-rejected" levels, in **two selectable modes** (you asked for both):
- `swing` — LTF swing pivots (fractal highs/lows) that left a real rejection wick.
- `h4candle` — extremes of recently closed H4 candles whose wick shows rejection.

Each gives, for every M15 bar, the nearest active support below and resistance
above.

**3. Entries + risk — `tfm_engine.py`**
When the M15 retests a level **in the H4 direction** and prints a fresh rejection
candle, enter: longs at rejected support in an uptrend, shorts at rejected
resistance in a downtrend. Stop beyond the rejection extreme (+ ATR buffer),
take-profit at fixed RR. Costs (round-trip spread + ATR slippage on stop fills)
are charged via the parent project's `v2_common.apply_costs`, so results are
**net** and comparable to the v2 tables.

Everything is **causal**: an H4 signal known at an H4 close is mapped forward to
M15 with `v2_common.causal_map`; swing pivots only appear after their right-side
confirmation. No look-ahead.

## Files

| File | What it is |
|---|---|
| `direction_model.py` | Pluggable H4 forecaster: TimesFM 2.5 + baseline, quantile-gated signal |
| `levels.py` | Visited-and-rejected level detection (`swing` and `h4candle` modes) |
| `tfm_engine.py` | Combines direction + LTF rejection entries; cost-aware trade log |
| `run_tfm.py` | Walk-forward runner (train ≤ 2024-12-31, test 2025-01-01 →) |
| `smoke_test.py` | End-to-end test on synthetic data — no project data / TimesFM needed |
| `requirements.txt` | Deps (core + optional TimesFM/torch) |
| `results/` | Created on first run: `summary.csv` + per-config trade logs |

## Quick start

From inside this folder.

```bash
# 0) verify the wiring (synthetic data, no deps beyond pandas/numpy)
python smoke_test.py

# 1) run on your real data with the baseline forecaster, both level modes
python run_tfm.py --forecaster baseline

# 2) run with the real TimesFM 2.5 model
pip install -r requirements.txt        # installs timesfm + torch
python run_tfm.py --forecaster timesfm
```

Useful flags: `--symbol XAUUSD --ltf m15 --level-mode {both,swing,h4candle}
--rr 3.0 --horizon 6 --min-move-frac 0.0015 --max-hold 64`.

### Data

`run_tfm.py` reads the parquet layout `data/<tf>/<SYMBOL>_<TF>.parquet`
(a self-contained copy lives in this project's `data/` folder) and builds
NY-17:00-anchored H4 via `v2_common.resample_h4_ny`. Default target is
**XAUUSD H4→M15**. This project is standalone — no external folders needed.

## Status / what was verified here

- ✅ Full pipeline runs end-to-end and produces cost-adjusted trades in **both**
  level modes (verified via `smoke_test.py` on synthetic data).
- ⚠️ The real TimesFM model was **not** executed in the build sandbox: it has no
  network access to PyTorch/HuggingFace, so `torch` and the checkpoint can't be
  fetched there. The `TimesFMForecaster` is wired to the documented 2.5 API
  (`TimesFM_2p5_200M_torch.from_pretrained` + `ForecastConfig` + `forecast`); run
  step (2) above on your machine to exercise it. If the upstream API shifts,
  it's isolated to `TimesFMForecaster._load` / `.predict`.

## Notes & honest caveats

- **The baseline forecaster is not a strategy.** Strong smoke-test numbers come
  from clean synthetic trends; ignore them. Real evaluation = TimesFM on real
  data through the walk-forward split.
- **Same discipline as the rest of the suite**: judge a config on the untouched
  2025–2026 **test** column, net of costs — not on train.
- **Cost sensitivity**: M15 entries were chosen (over M5) precisely because wider
  risk distances keep cost-per-R low; the engine prints `avg_cost_r` so you can
  watch it.
- TimesFM forecasts on *price levels* by default here. If you prefer, forecasting
  on returns or log-price is a one-line change in `direction_model.py`.

*Research/educational use only — not financial advice.*
