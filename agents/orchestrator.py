"""Layer 3 — Orchestrator decision node (regime-aware).

Consensus is a deterministic tally over the agents' structured votes plus a
price-vs-VWAP structural signal. Two upgrades over the naive N-of-5:

1. ABSTENTION-ROBUST CONSENSUS. We require a STRICT MAJORITY of the signals that
   actually expressed a direction, with a hard floor of `min_votes` (default 2).
   Agents that ABSTAIN (no data) simply don't participate, so they can never
   silently veto a trade. With all five voting this naturally reduces to the
   classic "3 of 5"; with two abstaining it becomes "2 of 3".

2. REGIME-AWARE STRUCTURAL ROLE (per the configured strategy):
       ORB breakout UP  (close > ORB high) -> TREND_UP -> structural = HARD FILTER
                                                          (VWAP enforced; veto trades
                                                           opposing the VWAP side)
       ORB breakout DOWN (close < ORB low) -> REVERSAL -> structural = advisory vote
       No ORB break / no ORB              -> NEUTRAL  -> structural = advisory vote
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from core.enums import AgentVote, AssetClass, Bias, SetupType
from core.schemas import AgentSignal, ArmedSetup, KeyLevels, TradePlan, XSentimentSignal
from core.settings import get_settings
from features.regime import classify_regime as _regime  # shared classifier

_MIN_DIRECTIONAL_VOTES = 2  # absolute floor; majority does the rest

# X sentiment from high-velocity macro sources carries higher conviction than a
# single internal agent — volatility alerts in particular represent structural
# market threats, not just directional views.
_X_SENTIMENT_VOTE_WEIGHT = 1.5   # effective votes when vol_alert=True
_X_SENTIMENT_BASE_WEIGHT = 1.0   # effective votes when vol_alert=False

# Keys checked per asset class. orb_high/orb_low are equity-only — continuous
# assets (gold, crypto) have no opening range by construction.
_REQUIRED_KEYS_UNIVERSAL = ("last_close", "vwap", "atr")
_REQUIRED_KEYS_EQUITY = ("orb_high", "orb_low")


def _warn_if_snapshot_incomplete(fs: dict, asset_class: str = "equity") -> None:
    keys = _REQUIRED_KEYS_UNIVERSAL + (_REQUIRED_KEYS_EQUITY if asset_class == "equity" else ())
    missing = [k for k in keys if fs.get(k) is None]
    if missing:
        print(
            f"[orchestrator][WARN] feature_snapshot missing/None: {missing} "
            f"-> regime will default to NEUTRAL and the VWAP filter cannot fire. "
            f"Pass dataclasses.asdict(fs) with flat keys. Got keys: {sorted(fs.keys())}"
        )


# --------------------------------------------------------------------------- #
# Structural signal (regime classification delegated to features.regime)
# --------------------------------------------------------------------------- #
def _structural_vote(fs: dict) -> AgentVote:
    close, vwap = fs.get("last_close"), fs.get("vwap")
    if close is None or vwap is None:
        return AgentVote.ABSTAIN
    if close > vwap:
        return AgentVote.LONG
    if close < vwap:
        return AgentVote.SHORT
    return AgentVote.FLAT


# --------------------------------------------------------------------------- #
# Level derivation (unchanged geometry; gateway re-validates RR)
# --------------------------------------------------------------------------- #
def _derive_levels(fs: dict, bias: Bias) -> KeyLevels | None:
    close, vwap, atr = fs.get("last_close"), fs.get("vwap"), fs.get("atr")
    if close is None or atr is None:
        return None
    sup = sorted(fs.get("support_levels") or [])
    res = sorted(fs.get("resistance_levels") or [])
    if bias is Bias.LONG:
        stop = vwap if (vwap and vwap < close) else close - atr
        targets = [t for t in res if t > close][:2] or [close + 2 * (close - stop)]
        return KeyLevels(entry=close, stop=round(stop, 4), targets=[round(t, 4) for t in targets])
    if bias is Bias.SHORT:
        stop = vwap if (vwap and vwap > close) else close + atr
        targets = [t for t in sorted(sup, reverse=True) if t < close][:2] or [close - 2 * (stop - close)]
        return KeyLevels(entry=close, stop=round(stop, 4), targets=[round(t, 4) for t in targets])
    return None


# --------------------------------------------------------------------------- #
# Decision node
# --------------------------------------------------------------------------- #
def orchestrator_node(state: dict) -> dict:
    s = get_settings()
    fs = state.get("feature_snapshot", {})
    asset_class_str = str(state.get("asset_class", "equity")).lower()
    _warn_if_snapshot_incomplete(fs, asset_class_str)
    regime = _regime(fs)
    structural = _structural_vote(fs)

    # Extract the X sentiment signal (may be absent in backtest / lean mode)
    x_signal: XSentimentSignal | None = state.get("x_sentiment_signal")
    volatility_alert = x_signal.volatility_alert if x_signal is not None else False

    # structural participates as a vote in every regime; in TREND_UP it ALSO
    # acts as a hard filter (applied after the tally).
    # X sentiment votes carry a higher weight when a volatility alert is active.
    raw_signals: list[AgentSignal] = list(state.get("signals", []))
    long_n: float = 0.0
    short_n: float = 0.0

    for sig in raw_signals:
        if sig.vote not in (AgentVote.LONG, AgentVote.SHORT):
            continue
        weight = (
            _X_SENTIMENT_VOTE_WEIGHT if (sig.agent_name == "x_sentiment" and volatility_alert)
            else _X_SENTIMENT_BASE_WEIGHT
        )
        if sig.vote is AgentVote.LONG:
            long_n += weight
        else:
            short_n += weight

    # structural vote (1.0 weight — it is a deterministic price signal)
    if structural is AgentVote.LONG:
        long_n += 1.0
    elif structural is AgentVote.SHORT:
        short_n += 1.0

    # Keep integer-compatible tally for the floor logic below
    tally = Counter({AgentVote.LONG: long_n, AgentVote.SHORT: short_n})

    total_directional = long_n + short_n
    floor = float(max(_MIN_DIRECTIONAL_VOTES, state.get("consensus_threshold") or _MIN_DIRECTIONAL_VOTES))
    floor = min(floor, max(float(_MIN_DIRECTIONAL_VOTES), total_directional))

    if long_n > short_n and long_n >= floor:
        bias, score = Bias.LONG, long_n
    elif short_n > long_n and short_n >= floor:
        bias, score = Bias.SHORT, short_n
    else:
        bias, score = Bias.FLAT, max(long_n, short_n)

    # --- regime enforcement: VWAP hard filter on trend-up days ---
    filter_applied = False
    if regime == "trend_up" and bias is not Bias.FLAT and structural in (AgentVote.LONG, AgentVote.SHORT):
        structural_bias = Bias.LONG if structural is AgentVote.LONG else Bias.SHORT
        if bias is not structural_bias:
            bias, filter_applied = Bias.FLAT, True  # vetoed: trade opposes VWAP on a trend day

    now = datetime.now(timezone.utc)
    if bias is Bias.FLAT:
        levels = None
    else:
        # Prefer provider-supplied structural levels (CRT OB, ICT PD arrays) over
        # the generic equity VWAP/resistance derivation when a matching-direction
        # signal carries them.
        matching_vote = AgentVote.LONG if bias is Bias.LONG else AgentVote.SHORT
        provider_levels = next(
            (sig.proposed_levels for sig in state.get("signals", [])
             if sig.proposed_levels is not None and sig.vote is matching_vote),
            None,
        )
        levels = provider_levels or _derive_levels(fs, bias)
    if bias is not Bias.FLAT and levels is None:
        bias = Bias.FLAT

    plan = TradePlan(
        plan_id=str(uuid.uuid4()),
        symbol=state["symbol"],
        asset_class=AssetClass(state["asset_class"]),
        bias=bias,
        armed_setups=(
            [ArmedSetup(setup_type=SetupType.VWAP_RECLAIM, confidence=min(score / 5.0, 1.0))]
            if bias is not Bias.FLAT else []
        ),
        key_levels=levels,
        max_risk_pct=min(s.max_per_trade_risk_pct, 2.0),
        consensus_score=int(round(score)),
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        volatility_alert=volatility_alert,
    )
    return {
        "trade_plan": plan,
        "consensus_score": int(round(score)),
        "regime": regime,
        "structural_filter_applied": filter_applied,
        "volatility_alert": volatility_alert,
    }
