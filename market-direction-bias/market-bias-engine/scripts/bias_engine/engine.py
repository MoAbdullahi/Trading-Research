"""The bias engine: compute per-bar bias and a current_bias() summary.

Pipeline per bar:
  1. Each factor casts a -1/0/+1 vote (see factors.py).
  2. The composite score is the weighted sum of votes -> raw score in [-1, +1].
  3. The ADX regime gate decides trending vs ranging. In a ranging regime the
     score is halved and the neutral band widened, so the engine declines to
     force a direction in chop.
  4. The (gated) effective score is thresholded against the neutral band into
     a final bias of -1 / 0 / +1.

The whole thing is deterministic: same bars in, same bias out. There is no
fitting, no randomness, no hidden state -- which is exactly what you want from
the layer that a TradePlan will lean on.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional, Union

import pandas as pd

import pyindicators as pi

from .config import BiasConfig
from .factors import FACTORS, Vote


LABELS = {1: "bullish", -1: "bearish", 0: "neutral"}

# Columns the engine adds. Per-factor vote columns are bias_vote_<key>.
SCORE_COL = "bias_score"
EFFECTIVE_COL = "bias_effective_score"
REGIME_COL = "bias_regime"
BIAS_COL = "bias"
LABEL_COL = "bias_label"


@dataclass
class Component:
    """One factor's contribution to a single bias decision."""
    name: str
    vote: int
    weight: float
    contribution: float   # vote * weight, before the regime gate
    detail: str

    def to_dict(self):
        return asdict(self)


@dataclass
class BiasResult:
    """The transparent summary returned by current_bias()."""
    bias: int                 # -1 / 0 / +1
    label: str                # bearish / neutral / bullish
    score: float              # raw weighted vote sum, [-1, +1]
    effective_score: float    # after the regime gate
    regime: str               # "trending" / "ranging"
    adx: Optional[float]
    neutral_band: float       # band actually applied (widens when ranging)
    components: List[Component]
    index: object = None      # the bar's index label (e.g. timestamp)

    def to_dict(self):
        d = asdict(self)
        d["index"] = None if self.index is None else str(self.index)
        return d

    def breakdown_table(self) -> str:
        """Human-readable component breakdown -- the 'show your work' view."""
        lines = []
        lines.append(f"Bias: {self.label.upper()} ({self.bias:+d})")
        lines.append(
            f"Score: {self.score:+.3f} raw -> {self.effective_score:+.3f} effective "
            f"| regime: {self.regime} (ADX "
            f"{'n/a' if self.adx is None else format(self.adx, '.1f')}) "
            f"| neutral band: +/-{self.neutral_band:.2f}"
        )
        if self.index is not None:
            lines.append(f"Bar: {self.index}")
        lines.append("-" * 64)
        lines.append(f"{'factor':<18}{'vote':>5}{'weight':>9}{'contrib':>10}   reason")
        for c in self.components:
            lines.append(
                f"{c.name:<18}{c.vote:>+5d}{c.weight:>9.2f}{c.contribution:>+10.3f}   {c.detail}"
            )
        lines.append("-" * 64)
        return "\n".join(lines)


class BiasEngine:
    """Deterministic multi-factor bias layer built on PyIndicators.

    Typical use::

        engine = BiasEngine()                 # defaults match the spec
        df = engine.compute(ohlc)             # per-bar columns
        result = engine.current_bias(ohlc)    # latest bar + breakdown
        print(result.breakdown_table())

    For ablation, pass a config with a zeroed weight::

        from bias_engine import BiasConfig, FactorWeights
        cfg = BiasConfig(weights=FactorWeights(supertrend=0.0))
        BiasEngine(cfg).current_bias(ohlc)
    """

    REQUIRED_COLUMNS = ("High", "Low", "Close")

    def __init__(self, config: Optional[BiasConfig] = None):
        self.config = config or BiasConfig()

    # -- indicator layer --------------------------------------------------
    def _ensure_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Run the underlying PyIndicators if their columns aren't present.

        We only compute what's missing, so you can pass a frame that already
        has some indicators and the engine won't clobber them.
        """
        missing = [c for c in self.REQUIRED_COLUMNS if c not in data.columns]
        if missing:
            raise ValueError(
                f"input is missing required OHLC column(s): {missing}. "
                f"Provide a DataFrame with at least {self.REQUIRED_COLUMNS}."
            )
        cfg = self.config
        df = data.copy()

        if "ADX" not in df.columns:
            df = pi.adx(df, period=cfg.adx_period)
        if "supertrend_trend" not in df.columns:
            df = pi.supertrend(
                df, atr_length=cfg.supertrend_atr_length, factor=cfg.supertrend_factor
            )
        if "market_trend" not in df.columns:
            df = pi.market_structure_choch_bos(df, length=cfg.structure_length)
        if "swing_direction" not in df.columns:
            df = pi.swing_structure(df, swing_length=cfg.swing_length)
        if "pdz_zone" not in df.columns:
            df = pi.premium_discount_zones(df, swing_length=cfg.pdz_swing_length)
        return df

    # -- scoring core (single bar) ---------------------------------------
    def _score_bar(self, bar) -> BiasResult:
        cfg = self.config
        weights = cfg.effective_weights()
        wd = weights.as_dict()

        components: List[Component] = []
        score = 0.0
        for key, weight_attr, fn in FACTORS:
            vote: Vote = fn(bar, cfg)
            w = wd[weight_attr]
            contrib = vote.direction * w
            score += contrib
            components.append(
                Component(
                    name=key, vote=vote.direction, weight=w,
                    contribution=contrib, detail=vote.detail,
                )
            )

        adx = bar.get("ADX")
        adx_val = None if (adx is None or pd.isna(adx)) else float(adx)
        ranging = adx_val is not None and adx_val < cfg.adx_ranging_threshold

        if ranging:
            effective = score * cfg.ranging_score_multiplier
            band = cfg.neutral_band_ranging
            regime = "ranging"
        else:
            effective = score
            band = cfg.neutral_band
            regime = "trending"

        if effective > band:
            bias = 1
        elif effective < -band:
            bias = -1
        else:
            bias = 0

        return BiasResult(
            bias=bias, label=LABELS[bias], score=round(score, 6),
            effective_score=round(effective, 6), regime=regime, adx=adx_val,
            neutral_band=band, components=components,
            index=bar.name if hasattr(bar, "name") else None,
        )

    # -- public API -------------------------------------------------------
    def compute(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of ``data`` with per-bar bias columns appended.

        Adds: bias_vote_<factor> for each factor, plus bias_score,
        bias_effective_score, bias_regime, bias, and bias_label.
        """
        df = self._ensure_indicators(data)
        cfg = self.config
        weights = cfg.effective_weights().as_dict()

        vote_cols = {f"bias_vote_{k}": [] for k, _, _ in FACTORS}
        scores, effs, regimes, biases, labels = [], [], [], [], []

        for _, bar in df.iterrows():
            res = self._score_bar(bar)
            for comp in res.components:
                vote_cols[f"bias_vote_{comp.name}"].append(comp.vote)
            scores.append(res.score)
            effs.append(res.effective_score)
            regimes.append(res.regime)
            biases.append(res.bias)
            labels.append(res.label)

        out = df.copy()
        for col, vals in vote_cols.items():
            out[col] = vals
        out[SCORE_COL] = scores
        out[EFFECTIVE_COL] = effs
        out[REGIME_COL] = regimes
        out[BIAS_COL] = biases
        out[LABEL_COL] = labels
        return out

    def current_bias(self, data: pd.DataFrame) -> BiasResult:
        """Score only the most recent bar and return the full breakdown.

        This is the method a TradePlan calls: it gets the final bias plus a
        component-by-component account of how that bias was reached.
        """
        df = self._ensure_indicators(data)
        if len(df) == 0:
            raise ValueError("cannot compute current_bias on an empty frame")
        return self._score_bar(df.iloc[-1])
