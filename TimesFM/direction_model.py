"""
Direction models for the TimesFM test.

Idea
----
Direction is decided on the HIGHER timeframe (H4). A forecaster looks at a
trailing context window of H4 closes and predicts the next `horizon` closes
together with quantiles. We turn that into a discrete bias per H4 bar:

    +1  bullish   (forecast says price ends higher, with confidence)
    -1  bearish   (forecast says price ends lower, with confidence)
     0  flat / no-trade

All forecasters here are CAUSAL: the signal stamped on an H4 bar that CLOSES at
time t uses only closes up to and including t. The engine then maps that signal
forward onto the lower timeframe with `v2_common.causal_map`, so there is no
look-ahead.

Two interchangeable implementations:

  * BaselineForecaster  - no heavy deps, always runnable. A drift + empirical
                          quantile model over recent log-returns. Lets you test
                          the WHOLE pipeline (levels, entries, costs, walk-fwd)
                          before/without the foundation model.

  * TimesFMForecaster   - the real Google TimesFM 2.5 model. Same interface, so
                          the engine doesn't care which one it gets.

Both return a `DirectionResult` with one row per H4 bar.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------
@dataclass
class DirectionResult:
    """Per-H4-bar direction signal, indexed by H4 bar CLOSE time (UTC ns)."""
    signal: pd.Series          # int in {-1, 0, +1}, index = H4 close time
    median_fc: pd.Series       # median forecast level at the horizon
    lo: pd.Series              # lower-quantile forecast level at the horizon
    hi: pd.Series              # upper-quantile forecast level at the horizon
    last_close: pd.Series      # the H4 close the forecast was made from

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame({
            "last_close": self.last_close,
            "median_fc": self.median_fc,
            "lo": self.lo,
            "hi": self.hi,
            "signal": self.signal,
        })


# ---------------------------------------------------------------------------
# Shared signal logic: "median forecast + quantile gate"
# ---------------------------------------------------------------------------
def _signal_from_quantiles(last_close: float,
                           median_fc: float,
                           lo: float,
                           hi: float,
                           min_move_frac: float) -> int:
    """
    Median forecast + quantile gate.

    Bullish requires BOTH:
        median_fc > last_close * (1 + min_move_frac)   (meaningful up move)
        lo        > last_close                          (even the low quantile
                                                          is above now -> the
                                                          forecast band clears
                                                          the current price)
    Bearish is the mirror image with `hi < last_close`.
    Otherwise 0 (no trade) — the band straddles the current price, i.e. the
    model is not confident about direction.
    """
    up_move = median_fc > last_close * (1.0 + min_move_frac)
    dn_move = median_fc < last_close * (1.0 - min_move_frac)
    if up_move and lo > last_close:
        return 1
    if dn_move and hi < last_close:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Baseline (always available) forecaster
# ---------------------------------------------------------------------------
class BaselineForecaster:
    """
    Lightweight stand-in for TimesFM so the pipeline is testable everywhere.

    For each H4 bar it takes the last `context` log-returns, estimates a drift
    (mean) and dispersion (std), and projects `horizon` steps ahead:

        median_fc = last_close * exp(drift * horizon)
        lo/hi     = last_close * exp((drift -/+ z*std*sqrt(horizon)))

    This is deliberately simple; it is NOT meant to be predictive, only to
    exercise every downstream component with realistic-looking signals.
    """

    name = "baseline"

    def __init__(self, context: int = 64, horizon: int = 6,
                 z: float = 0.8, min_move_frac: float = 0.0015):
        self.context = int(context)
        self.horizon = int(horizon)
        self.z = float(z)
        self.min_move_frac = float(min_move_frac)

    def predict(self, h4: pd.DataFrame) -> DirectionResult:
        close = h4["close"].to_numpy(dtype=float)
        idx = h4.index
        n = len(close)
        logc = np.log(close)
        ret = np.diff(logc, prepend=logc[0])

        med = np.full(n, np.nan)
        lo = np.full(n, np.nan)
        hi = np.full(n, np.nan)
        sig = np.zeros(n, dtype=int)

        h = self.horizon
        for i in range(n):
            j0 = max(0, i - self.context + 1)
            window = ret[j0:i + 1]
            if len(window) < max(8, self.context // 4):
                continue
            drift = float(np.mean(window))
            sd = float(np.std(window))
            lc = close[i]
            med[i] = lc * np.exp(drift * h)
            band = self.z * sd * np.sqrt(h)
            lo[i] = lc * np.exp(drift * h - band)
            hi[i] = lc * np.exp(drift * h + band)
            sig[i] = _signal_from_quantiles(lc, med[i], lo[i], hi[i],
                                            self.min_move_frac)

        return DirectionResult(
            signal=pd.Series(sig, index=idx),
            median_fc=pd.Series(med, index=idx),
            lo=pd.Series(lo, index=idx),
            hi=pd.Series(hi, index=idx),
            last_close=pd.Series(close, index=idx),
        )


# ---------------------------------------------------------------------------
# Real TimesFM 2.5 forecaster
# ---------------------------------------------------------------------------
class TimesFMForecaster:
    """
    Google TimesFM 2.5 (200M) wrapper, same interface as BaselineForecaster.

    Requires:  pip install timesfm torch   (see requirements.txt)
    First run downloads the checkpoint from HuggingFace
    (google/timesfm-2.5-200m-pytorch), so you need network access once.

    We run TimesFM in BATCH over a rolling set of context windows. To keep
    memory/time sane on a long M15-derived H4 series we forecast on a stride
    (every `stride` bars) and forward-fill the signal between recomputes; set
    stride=1 for a forecast on every bar.

    Quantile head: TimesFM returns 10 quantiles (10%..90% + mean-ish). We use
    the median (~50%) for `median_fc` and configurable low/high quantiles for
    the gate.
    """

    name = "timesfm-2.5-200m"

    def __init__(self, context: int = 512, horizon: int = 6,
                 stride: int = 1, min_move_frac: float = 0.0015,
                 lo_q: int = 2, hi_q: int = 8,
                 checkpoint: str = "google/timesfm-2.5-200m-pytorch",
                 batch_size: int = 256):
        self.context = int(context)
        self.horizon = int(horizon)
        self.stride = max(1, int(stride))
        self.min_move_frac = float(min_move_frac)
        self.lo_q = int(lo_q)       # index into the 10-quantile output (1..9 -> 10%..90%)
        self.hi_q = int(hi_q)
        self.checkpoint = checkpoint
        self.batch_size = int(batch_size)
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        import torch
        import timesfm
        torch.set_float32_matmul_precision("high")
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(self.checkpoint)
        model.compile(
            timesfm.ForecastConfig(
                max_context=self.context,
                max_horizon=self.horizon,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
        self._model = model

    def predict(self, h4: pd.DataFrame) -> DirectionResult:
        self._load()
        close = h4["close"].to_numpy(dtype=float)
        idx = h4.index
        n = len(close)

        # Bars we will actually run the model on.
        eval_pos = list(range(self.context, n, self.stride))
        if not eval_pos:
            empty = pd.Series(np.nan, index=idx)
            return DirectionResult(pd.Series(0, index=idx), empty, empty,
                                   empty, pd.Series(close, index=idx))

        contexts = [close[p - self.context:p] for p in eval_pos]

        med_at = {}
        lo_at = {}
        hi_at = {}
        for b in range(0, len(contexts), self.batch_size):
            chunk = contexts[b:b + self.batch_size]
            point_fc, quant_fc = self._model.forecast(
                horizon=self.horizon, inputs=chunk)
            # point_fc: (B, H)  quant_fc: (B, H, 10)
            point_fc = np.asarray(point_fc)
            quant_fc = np.asarray(quant_fc)
            for k, p in enumerate(eval_pos[b:b + self.batch_size]):
                med_at[p] = float(point_fc[k, self.horizon - 1])
                lo_at[p] = float(quant_fc[k, self.horizon - 1, self.lo_q])
                hi_at[p] = float(quant_fc[k, self.horizon - 1, self.hi_q])

        med = np.full(n, np.nan)
        lo = np.full(n, np.nan)
        hi = np.full(n, np.nan)
        sig = np.zeros(n, dtype=int)
        last_med = last_lo = last_hi = np.nan
        last_sig = 0
        for i in range(n):
            if i in med_at:
                last_med, last_lo, last_hi = med_at[i], lo_at[i], hi_at[i]
                last_sig = _signal_from_quantiles(
                    close[i], last_med, last_lo, last_hi, self.min_move_frac)
            if i >= self.context:
                med[i], lo[i], hi[i], sig[i] = (
                    last_med, last_lo, last_hi, last_sig)

        return DirectionResult(
            signal=pd.Series(sig, index=idx),
            median_fc=pd.Series(med, index=idx),
            lo=pd.Series(lo, index=idx),
            hi=pd.Series(hi, index=idx),
            last_close=pd.Series(close, index=idx),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def make_forecaster(kind: str = "baseline", **kw):
    kind = kind.lower()
    if kind in ("baseline", "base"):
        return BaselineForecaster(**kw)
    if kind in ("timesfm", "tfm", "timesfm-2.5", "timesfm25"):
        return TimesFMForecaster(**kw)
    raise ValueError(f"unknown forecaster kind: {kind!r}")
