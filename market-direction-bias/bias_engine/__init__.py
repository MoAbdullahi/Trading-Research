"""bias_engine -- a deterministic multi-factor market-direction layer.

A transparent, ablatable bias engine built on PyIndicators. Each factor casts
a -1/0/+1 vote with an explicit weight; an ADX regime gate keeps the engine
from forcing a direction in a range. Designed to drop in as the deterministic
bias layer feeding a TradePlan.

    from bias_engine import BiasEngine
    result = BiasEngine().current_bias(ohlc_df)
    print(result.breakdown_table())
"""

from .config import BiasConfig, FactorWeights
from .engine import BiasEngine, BiasResult, Component

__all__ = [
    "BiasEngine",
    "BiasResult",
    "Component",
    "BiasConfig",
    "FactorWeights",
]

__version__ = "0.1.0"
