"""Configuration for the multi-factor bias engine.

Everything that controls the engine's behaviour lives here, in plain data.
The point of pulling it all into one place is *ablatability*: to test whether
a factor is actually pulling its weight, you set its weight to 0.0 and re-run.
Nothing about the decision is hidden in code branches you can't see.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict


@dataclass(frozen=True)
class FactorWeights:
    """Weight each factor contributes to the composite bias score.

    The defaults reflect a deliberate hierarchy: market *structure*
    (CHoCH/BOS) is the dominant read on where price is trying to go, so it
    carries the most weight. Swing structure (the HH/HL vs LH/LL sequence)
    seconds it. The trend-following and location factors fill in confluence.

    The defaults sum to 1.0, which keeps the raw composite score in [-1, +1]
    and makes each weight directly readable as "max % of the vote this factor
    can swing". If you ablate a factor (set it to 0), you can either leave the
    others literal (score range shrinks, honest) or set
    ``BiasConfig.normalize_weights=True`` to renormalise the survivors back to
    1.0 for a like-for-like comparison.
    """

    structure: float = 0.35          # CHoCH / BOS market structure (dominant)
    swing: float = 0.20              # swing sequence: HH/HL (bull) vs LH/LL (bear)
    supertrend: float = 0.15         # ATR trailing-stop trend
    directional: float = 0.15        # +DI vs -DI (directional movement)
    premium_discount: float = 0.15   # location within the dealing range

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)

    def total(self) -> float:
        return sum(self.as_dict().values())

    def normalized(self) -> "FactorWeights":
        """Renormalise so the active (non-zero) weights sum to 1.0.

        Useful for ablation studies: drop a factor to 0 and the remaining
        factors keep the same *relative* importance instead of the score
        simply getting quieter.
        """
        t = self.total()
        if t == 0:
            return self
        return FactorWeights(**{k: v / t for k, v in self.as_dict().items()})


@dataclass(frozen=True)
class BiasConfig:
    """All knobs for the bias engine.

    Factor parameters are passed straight through to the underlying
    PyIndicators calls, so anything you'd tune on a chart you can tune here.
    The regime block is what makes the engine refuse to force a direction in
    chop; the premium/discount block is the one genuinely sign-ambiguous
    factor and is called out explicitly.
    """

    weights: FactorWeights = field(default_factory=FactorWeights)

    # --- factor parameters (forwarded to PyIndicators) -------------------
    structure_length: int = 5          # market_structure_choch_bos(length=)
    swing_length: int = 5              # swing_structure(swing_length=)
    supertrend_atr_length: int = 10
    supertrend_factor: float = 3.0
    adx_period: int = 14
    pdz_swing_length: int = 10         # premium_discount_zones(swing_length=)

    # Minimum gap between +DI and -DI for the directional factor to vote at
    # all. With margin 0 the factor always picks a side; raise it to make the
    # factor abstain when directional movement is genuinely balanced.
    di_margin: float = 0.0

    # Equilibrium deadband for the premium/discount factor, in "depth into
    # zone" percent (PyIndicators' pdz_zone_pct: 0 = at equilibrium, 100 = at
    # the range extreme). If price is less than this deep into its zone it's
    # effectively at fair value, so the factor abstains rather than casting a
    # full premium/discount vote off a hair above or below equilibrium. 0
    # disables the deadband (every premium/discount bar votes); 10-15 is a
    # reasonable starting point if you want the factor to only speak when price
    # is meaningfully into a zone.
    pd_equilibrium_band: float = 0.0

    # Regime-aware premium/discount. Location is a *mean-reversion* read: fading
    # premium / buying discount only makes sense when price is rotating inside a
    # range. In a strong trend that same read fights the trend (an uptrend lives
    # in premium, a downtrend in discount), so when this is True the factor only
    # votes in a ranging regime (ADX < adx_ranging_threshold) and abstains in a
    # trend. Set False to let it vote in every regime (the literal spec).
    pd_regime_aware: bool = True

    # --- ADX regime gate -------------------------------------------------
    # Below this ADX the market is treated as ranging. In a ranging regime we
    # do two things: halve the composite score (so weak confluence can't be
    # dressed up as conviction) and widen the neutral band (so the engine
    # returns "neutral" unless the read is genuinely strong). Together these
    # let the engine *refuse to call a direction* when there isn't one.
    adx_ranging_threshold: float = 20.0
    ranging_score_multiplier: float = 0.5

    # Decision thresholds on the (post-gate) score. A bar is bullish only if
    # the effective score clears +band, bearish below -band, else neutral.
    neutral_band: float = 0.10
    neutral_band_ranging: float = 0.30

    # --- premium / discount sign convention ------------------------------
    # In Smart-Money terms a *discount* (lower half of the range) is where you
    # want to be a buyer and a *premium* is where you want to be a seller, so
    # by default discount votes bullish (+1). Flip this to False if you'd
    # rather read "price holding in premium" as raw bullish strength.
    discount_is_bullish: bool = True

    # If True, weights are renormalised to sum to 1.0 before scoring. Leave
    # False to keep weights literal (recommended for transparency).
    normalize_weights: bool = False

    def effective_weights(self) -> FactorWeights:
        return self.weights.normalized() if self.normalize_weights else self.weights
