"""CRT (Candle Range Theory) + ICT Order Block signal provider for XAUUSD M15.

Sweep-reversal logic:
  1. Identify the completed H4 range candle (fixed UTC boundaries: 00/04/08/12/16/20).
  2. Detect a wick sweep of one range extreme within the current H4's M15 bars.
  3. Require a displacement candle (body >= displacement_atr_mult * ATR) after the sweep.
  4. Confirm MSS/CHoCH: a close after displacement must break the sweep-bar reaction high/low.
  5. Find the last OB (opposing-colour candle) between the sweep and the displacement.
  6. OB_ONLY filter: price must have already retraced to the OB before signalling.

Levels returned via proposed_levels so the orchestrator uses the structural
entry/stop/target directly rather than the equity VWAP/resistance heuristic.

H4 resampling uses fixed UTC offsets (label="left", closed="left") which are
stable across DST transitions — gold trades 24h so there is no meaningful "open".
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.enums import AgentVote
from core.schemas import AgentSignal, KeyLevels


@dataclass
class CRTParams:
    h4_rule: str = "4h"                  # UTC-aligned resample: 00/04/08/12/16/20
    displacement_atr_mult: float = 1.0   # reversal candle body >= this * M15 ATR
    atr_period: int = 14
    sweep_buffer_atr: float = 0.1        # stop sits this * ATR beyond the swept wick
    min_m15_bars: int = 60               # warmup guard (4 H4 candles @ 16 bars each)
    ob_use_body: bool = True             # True: OB boundary is body extreme; False: use wick


def _calc_atr(df: pd.DataFrame, period: int) -> float:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"],
         (df["high"] - pc).abs(),
         (df["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    return float(tr.ewm(alpha=1.0 / period, adjust=False).mean().iloc[-1])


def _abstain() -> list[AgentSignal]:
    return [
        AgentSignal(agent_name=n, vote=AgentVote.ABSTAIN, confidence=0.0)
        for n in ("technical", "macro", "sentiment", "risk_manager")
    ]


class CRTSignalProvider:
    """Sweep-reversal entries based on CRT H4 range + ICT OB.

    Returns proposed_levels (entry at OB boundary, stop beyond swept extreme,
    target at opposite range wall) so orchestrator does not overwrite them with
    equity-derived levels.
    """

    def __init__(self, params: CRTParams | None = None) -> None:
        self.p = params or CRTParams()

    def get_signals(
        self, fs: dict, window: pd.DataFrame | None = None, asset_class: str = "gold"
    ) -> list[AgentSignal]:
        if window is None or len(window) < self.p.min_m15_bars:
            return _abstain()
        result = self._detect(window)
        if result is None:
            return _abstain()
        vote, levels, rationale = result
        return [
            AgentSignal(
                agent_name="technical",
                vote=vote,
                confidence=0.75,
                rationale=rationale,
                proposed_levels=levels,
            ),
            AgentSignal(
                agent_name="risk_manager",
                vote=vote,
                confidence=0.6,
                rationale="CRT structural setup",
            ),
            AgentSignal(agent_name="macro", vote=AgentVote.ABSTAIN, confidence=0.0),
            AgentSignal(agent_name="sentiment", vote=AgentVote.ABSTAIN, confidence=0.0),
        ]

    # ------------------------------------------------------------------ #

    def _detect(self, w: pd.DataFrame) -> tuple | None:
        p = self.p
        atr = _calc_atr(w, p.atr_period)
        if atr <= 0:
            return None

        h4 = (
            w.resample(p.h4_rule, label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
        if len(h4) < 2:
            return None

        range_high = float(h4["high"].iloc[-2])
        range_low = float(h4["low"].iloc[-2])

        cur = w[w.index >= h4.index[-1]]
        if len(cur) < 3:
            return None

        swept_low = float(cur["low"].min()) < range_low
        swept_high = float(cur["high"].max()) > range_high

        if swept_low == swept_high:  # both or neither — ambiguous, skip
            return None

        body = cur["close"] - cur["open"]

        if swept_low:
            return self._bullish(cur, w.iloc[-1], body, atr, range_low, range_high)
        return self._bearish(cur, w.iloc[-1], body, atr, range_low, range_high)

    def _bullish(self, cur, last, body, atr, range_low, range_high):
        p = self.p
        si = int(cur["low"].values.argmin())
        sweep_extreme = float(cur["low"].iloc[si])
        react_high = float(cur["high"].iloc[si])

        if last["close"] <= range_low:
            return None

        # displacement: first bullish body >= threshold after the sweep bar
        is_disp = (body >= p.displacement_atr_mult * atr) & (cur["close"] > cur["open"])
        disp_idxs = [i for i in is_disp.values.nonzero()[0] if i > si]
        if not disp_idxs:
            return None
        fd = disp_idxs[0]

        # MSS: a close after displacement must exceed the reaction high at the sweep bar
        if float(cur["close"].iloc[fd:].max()) <= react_high:
            return None

        # OB: last bearish bar between sweep and displacement (inclusive of sweep bar)
        ob = next(
            (cur.iloc[j] for j in range(fd - 1, si - 1, -1)
             if cur["close"].iloc[j] < cur["open"].iloc[j]),
            None,
        )
        if ob is None:
            return None

        ob_high = (float(max(ob["open"], ob["close"])) if p.ob_use_body
                   else float(ob["high"]))

        # OB_ONLY: price must have already retraced to the OB (last bar's low <= OB high)
        if last["low"] > ob_high:
            return None

        entry = ob_high
        stop = round(sweep_extreme - p.sweep_buffer_atr * atr, 4)
        target = round(range_high, 4)

        if not (stop < entry < target):
            return None

        lv = KeyLevels(entry=round(entry, 4), stop=stop, targets=[target])
        why = f"CRT long: swept {range_low:.2f}, displaced>{react_high:.2f}, OB retrace"
        return AgentVote.LONG, lv, why

    def _bearish(self, cur, last, body, atr, range_low, range_high):
        p = self.p
        si = int(cur["high"].values.argmax())
        sweep_extreme = float(cur["high"].iloc[si])
        react_low = float(cur["low"].iloc[si])

        if last["close"] >= range_high:
            return None

        is_disp = (body <= -p.displacement_atr_mult * atr) & (cur["close"] < cur["open"])
        disp_idxs = [i for i in is_disp.values.nonzero()[0] if i > si]
        if not disp_idxs:
            return None
        fd = disp_idxs[0]

        if float(cur["close"].iloc[fd:].min()) >= react_low:
            return None

        ob = next(
            (cur.iloc[j] for j in range(fd - 1, si - 1, -1)
             if cur["close"].iloc[j] > cur["open"].iloc[j]),
            None,
        )
        if ob is None:
            return None

        ob_low = (float(min(ob["open"], ob["close"])) if p.ob_use_body
                  else float(ob["low"]))

        if last["high"] < ob_low:
            return None

        entry = ob_low
        stop = round(sweep_extreme + p.sweep_buffer_atr * atr, 4)
        target = round(range_low, 4)

        if not (target < entry < stop):
            return None

        lv = KeyLevels(entry=round(entry, 4), stop=stop, targets=[target])
        why = f"CRT short: swept {range_high:.2f}, displaced<{react_low:.2f}, OB retrace"
        return AgentVote.SHORT, lv, why
