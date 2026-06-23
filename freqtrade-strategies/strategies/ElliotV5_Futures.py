"""
ElliotV5_Futures
================
Futures-enabled variant of ElliotV5_SMA_ninja for leverage-scaling experiments.

Entry/exit logic is inherited unchanged from the long-only spot strategy
ElliotV5_SMA_ninja (which already uses the modern Freqtrade entry/exit API, so
it is compatible with futures trading mode). The only addition is a configurable
leverage applied via the leverage() callback, letting the same signals be
backtested at 1x, 2x, 3x, 5x ... to study how leverage scales returns, drawdown
and liquidation risk.

Leverage is read from the FT_LEVERAGE environment variable (default 3.0), so the
same file can be swept across leverage levels without edits:

    FT_LEVERAGE=2 freqtrade backtesting --strategy ElliotV5_Futures ...

Note: this is LONG-ONLY (can_short = False). Leverage amplifies the existing
long edge; it does not add a new directional (short) edge.
"""
import os
from ElliotV5_SMA_ninja import ElliotV5_SMA_ninja


class ElliotV5_Futures(ElliotV5_SMA_ninja):
    can_short: bool = False

    def leverage(self, pair: str, current_time, current_rate: float,
                 proposed_leverage: float, max_leverage: float, side: str,
                 **kwargs) -> float:
        """Return the configured leverage, capped by the exchange maximum."""
        try:
            lev = float(os.environ.get("FT_LEVERAGE", "3"))
        except (TypeError, ValueError):
            lev = 3.0
        return max(1.0, min(lev, max_leverage))
