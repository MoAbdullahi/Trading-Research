from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict
@dataclass(frozen=True)
class FactorWeights:
    structure: float = 0.35
    swing: float = 0.20
    supertrend: float = 0.15
    directional: float = 0.15
    premium_discount: float = 0.15
    def as_dict(self): return asdict(self)
    def total(self): return sum(self.as_dict().values())
    def normalized(self):
        t=self.total()
        return self if t==0 else FactorWeights(**{k:v/t for k,v in self.as_dict().items()})
@dataclass(frozen=True)
class BiasConfig:
    weights: FactorWeights = field(default_factory=FactorWeights)
    structure_length: int = 5
    swing_length: int = 5
    supertrend_atr_length: int = 10
    supertrend_factor: float = 3.0
    adx_period: int = 14
    pdz_swing_length: int = 10
    di_margin: float = 0.0
    pd_equilibrium_band: float = 0.0
    pd_regime_aware: bool = True
    adx_ranging_threshold: float = 20.0
    ranging_score_multiplier: float = 0.5
    neutral_band: float = 0.10
    neutral_band_ranging: float = 0.30
    discount_is_bullish: bool = True
    normalize_weights: bool = False
    def effective_weights(self):
        return self.weights.normalized() if self.normalize_weights else self.weights
