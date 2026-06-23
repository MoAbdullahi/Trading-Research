"""Layer 3 — the four specialized agents.

Each agent is a LangGraph node: it reads GraphState, calls an LLM, and returns a
*structured* AgentSignal. The LLM is asked to return strict JSON so the
orchestrator's consensus tally stays deterministic (it never parses prose).

LLM wiring is intentionally abstracted behind `_call_llm`; drop in your provider
(Anthropic shown) without touching agent logic. Macro/Sentiment route to the
fast model; the Risk agent and final consensus use the reasoning model.
"""
from __future__ import annotations

import json
from typing import Any

from core.enums import AgentVote, AssetClass
from core.schemas import AgentSignal
from core.settings import get_settings

# --------------------------------------------------------------------------- #
# LLM transport (stub) — replace body, keep signature
# --------------------------------------------------------------------------- #
def _call_llm(model: str, system: str, user: str) -> str:
    """Anthropic-backed transport. ANY failure (network, auth, rate limit) is
    swallowed into an ABSTAIN signal so the graph degrades to NO-TRADE rather
    than crashing or guessing."""
    from agents.llm import call_anthropic

    try:
        return call_anthropic(model, system, user)
    except Exception as exc:  # noqa: BLE001 - intentional safe fallback
        return json.dumps(
            {"vote": "abstain", "confidence": 0.0, "rationale": f"llm_error:{type(exc).__name__}"}
        )


def _parse_signal(agent_name: str, raw: str) -> AgentSignal:
    """Defensive JSON parse -> AgentSignal. Malformed -> ABSTAIN (never crash the graph)."""
    try:
        data: dict[str, Any] = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return AgentSignal(
            agent_name=agent_name,
            vote=AgentVote(data["vote"]),
            confidence=float(data.get("confidence", 0.0)),
            rationale=str(data.get("rationale", ""))[:500],
            raw_response=raw,
        )
    except Exception:
        return AgentSignal(agent_name=agent_name, vote=AgentVote.ABSTAIN,
                           confidence=0.0, rationale="unparseable", raw_response=raw)


_JSON_CONTRACT = (
    'Respond with ONLY this JSON, no prose: '
    '{"vote": "long|short|flat|abstain", "confidence": 0.0-1.0, "rationale": "<=2 sentences"}'
)


# --------------------------------------------------------------------------- #
# 1. Technical Analyst — applies SETUP-APPROPRIATE criteria per regime.
#    The bug this fixes: reversal criteria (RSI<10/>90) were being applied in
#    every regime, so a clean trend_up breakout could never be approved.
# --------------------------------------------------------------------------- #
_TECH_CRITERIA = {
    "trend_up": (
        "TREND-CONTINUATION regime: price broke ABOVE the opening range. This is "
        "momentum, NOT reversal — do NOT require RSI extremes. Vote LONG only if ALL "
        "hold: price is above VWAP, RVOL >= 2.0 (genuine participation), and the 9/20 "
        "EMAs sit below price (intact momentum). If price is losing VWAP or volume is "
        "thin, vote FLAT. Never vote SHORT against an up-breakout here."
    ),
    "reversal": (
        "REVERSAL regime: price broke BELOW the opening range. Apply Aziz's STRICT "
        "reversal criteria and nothing looser: vote LONG only if RSI < 10 (climax "
        "oversold) AND RVOL >= 2.0 (capitulation) AND price is at/below a major support "
        "level showing exhaustion. Mirror for SHORT at RSI > 90 into resistance. "
        "Anything short of that is FLAT — do not catch a falling knife."
    ),
    "neutral": (
        "NEUTRAL regime: price is inside the opening range — no breakout, no climax. "
        "Default to FLAT. Only vote directionally on a clean VWAP reclaim with RVOL "
        ">= 1.5 in the direction of the reclaim. Be conservative."
    ),
}


def technical_agent(state: dict) -> dict:
    from features.regime import classify_regime

    s = get_settings()
    fs = state.get("feature_snapshot", {})
    regime = classify_regime(fs)
    system = (
        "You are a technical analyst applying Andrew Aziz's day-trading setup rules. "
        f"{_TECH_CRITERIA[regime]} Judge level confluence and candle structure within "
        "those rules. " + _JSON_CONTRACT
    )
    user = f"Regime: {regime}\nFeature snapshot:\n{json.dumps(fs, default=str, indent=2)}"
    raw = _call_llm(s.fast_model, system, user)
    return {"signals": [_parse_signal("technical", raw)]}


# --------------------------------------------------------------------------- #
# 2. Macro / Context — parameters switch on asset class
# --------------------------------------------------------------------------- #
_MACRO_FOCUS = {
    AssetClass.EQUITY: "earnings dates, SEC filings, float, short interest",
    AssetClass.FOREX: "economic calendar: CPI, rate decisions, NFP",
    AssetClass.GOLD: "real yields, DXY momentum, risk-off sentiment",
    AssetClass.CRYPTO: "on-chain flows, exchange stablecoin in/outflows, regulatory headlines",
}


def macro_agent(state: dict) -> dict:
    s = get_settings()
    ac = AssetClass(state["asset_class"])
    focus = _MACRO_FOCUS[ac]
    system = (
        f"You are a macro/context analyst for {ac.value}. Evaluate ONLY: {focus}. "
        "Decide whether the macro backdrop supports the direction. " + _JSON_CONTRACT
    )
    user = f"Context:\n{json.dumps(state.get('macro_context', {}), default=str, indent=2)}"
    raw = _call_llm(s.fast_model, system, user)
    return {"signals": [_parse_signal("macro", raw)]}


# --------------------------------------------------------------------------- #
# 3. Sentiment
# --------------------------------------------------------------------------- #
def sentiment_agent(state: dict) -> dict:
    s = get_settings()
    system = (
        "You are a financial-sentiment analyst. Aggregate news/social tone into a "
        "directional lean. Use a domain NLP model (FinBERT/FinGPT) upstream for raw "
        "scores; you arbitrate conflicts. " + _JSON_CONTRACT
    )
    user = f"News items:\n{json.dumps(state.get('news_items', []), default=str, indent=2)}"
    raw = _call_llm(s.fast_model, system, user)
    return {"signals": [_parse_signal("sentiment", raw)]}


# --------------------------------------------------------------------------- #
# 4. Risk Manager — uses the deep model, checks cross-asset correlation
# --------------------------------------------------------------------------- #
def risk_manager_agent(state: dict) -> dict:
    s = get_settings()
    system = (
        "You are a risk manager. Given live account state and existing exposure, "
        "judge whether ADDING this position stacks unhedged correlated risk "
        "(e.g. long Gold + short DXY + long equities). Vote flat if it does. "
        "You do NOT size positions — the deterministic gateway does. " + _JSON_CONTRACT
    )
    user = (
        f"Account:\n{json.dumps(state.get('account_snapshot', {}), default=str, indent=2)}\n"
        f"Proposed direction context:\n{json.dumps(state.get('feature_snapshot', {}), default=str, indent=2)}"
    )
    raw = _call_llm(s.reasoning_model, system, user)
    return {"signals": [_parse_signal("risk_manager", raw)]}
