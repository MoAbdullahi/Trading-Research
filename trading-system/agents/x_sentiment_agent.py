"""LangGraph node — X sentiment agent.

Gate: if volume_spike_ratio < VOLUME_GATE_THRESHOLD, bypass LLM instantly and
emit a static NEUTRAL signal.  This eliminates all token cost and latency for
the vast majority of bars where X is quiet.

When the gate passes, invokes ChatAnthropic with structured output
(XSentimentSignal) wrapped in asyncio.wait_for(timeout=3s).  A timeout or any
LLM error falls back to NEUTRAL with volatility_alert=False so the graph
degrades gracefully instead of crashing.

Prometheus metrics are registered lazily (no hard dependency on a running
Prometheus server — the module still imports and the metrics are no-ops if
prometheus_client is absent).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from core.schemas import XSentimentMetrics, XSentimentSignal

logger = logging.getLogger(__name__)

VOLUME_GATE_THRESHOLD = 2.0   # spike ratio below this → instant NEUTRAL
LLM_TIMEOUT_SECONDS = 3.0
SENTIMENT_AGENT_MODEL = "claude-haiku-4-5-20251001"   # fast, cheap; override via settings

# --------------------------------------------------------------------------- #
# Prometheus metrics (lazy import — no crash if prometheus_client absent)
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Counter, Histogram, Gauge

    _signals_total = Counter(
        "x_sentiment_signals_total",
        "Total X sentiment signals emitted",
        ["bias", "path"],        # path: "gate_bypass" or "llm"
    )
    _llm_latency = Histogram(
        "x_sentiment_llm_latency_seconds",
        "LangChain Anthropic invocation latency for X sentiment",
        buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0],
    )
    _timeout_total = Counter(
        "x_sentiment_llm_timeout_total",
        "Number of LLM invocations that exceeded the 3s timeout",
    )
    _false_positive_rate = Gauge(
        "x_sentiment_false_positive_rate",
        "Running estimate: vol_alert signals that did not result in a trade",
    )
    _PROM_OK = True
except ImportError:
    _PROM_OK = False
    logger.warning("prometheus_client not installed — metrics disabled")

    class _NoOp:  # minimal stub
        def labels(self, **_): return self
        def inc(self, *_): pass
        def observe(self, *_): pass
        def set(self, *_): pass

    _signals_total = _NoOp()
    _llm_latency = _NoOp()
    _timeout_total = _NoOp()
    _false_positive_rate = _NoOp()


# --------------------------------------------------------------------------- #
# Static fallback
# --------------------------------------------------------------------------- #
_NEUTRAL_SIGNAL = XSentimentSignal(
    sentiment_bias="NEUTRAL",
    conviction_score=0.0,
    volatility_alert=False,
    primary_catalyst_summary="volume gate not met or llm unavailable",
    source_tweet_ids=[],
)


def _make_neutral(reason: str, ids: list[str] | None = None) -> XSentimentSignal:
    return XSentimentSignal(
        sentiment_bias="NEUTRAL",
        conviction_score=0.0,
        volatility_alert=False,
        primary_catalyst_summary=reason,
        source_tweet_ids=ids or [],
    )


# --------------------------------------------------------------------------- #
# LLM invocation (async, with structured output)
# --------------------------------------------------------------------------- #
async def _invoke_llm(metrics: XSentimentMetrics) -> XSentimentSignal:
    from langchain_anthropic import ChatAnthropic
    from core.settings import get_settings

    s = get_settings()
    model_name = getattr(s, "fast_model", SENTIMENT_AGENT_MODEL)

    llm = ChatAnthropic(
        model=model_name,
        temperature=0.0,
        anthropic_api_key=s.anthropic_api_key,
    ).with_structured_output(XSentimentSignal)

    system = (
        "You are a zero-hallucination macro risk analyst. "
        "Only use the provided compressed samples. Never invent facts. "
        "Return a structured signal: sentiment_bias, conviction_score, "
        "volatility_alert, primary_catalyst_summary, source_tweet_ids."
    )

    user_content = (
        f"volume_spike_ratio: {metrics.volume_spike_ratio}\n"
        f"model_score: {metrics.model_score}\n"
        f"impact_score: {metrics.impact_score}\n"
        f"high_impact_samples:\n"
        + "\n".join(f"  - {s}" for s in metrics.high_impact_text_samples)
        + f"\nsource_tweet_ids: {metrics.source_tweet_ids[:10]}"
    )

    # Build messages for ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [SystemMessage(content=system), HumanMessage(content=user_content)]

    result = await llm.ainvoke(messages)
    return result


# --------------------------------------------------------------------------- #
# Public LangGraph node
# --------------------------------------------------------------------------- #
def x_sentiment_agent_node(state: dict) -> dict:
    """Synchronous LangGraph node wrapper.  Uses asyncio to run the async LLM
    call with a hard 3-second timeout.  Falls back to NEUTRAL on any failure.
    """
    metrics: Optional[XSentimentMetrics] = state.get("x_sentiment_metrics")

    if metrics is None:
        signal = _make_neutral("no metrics in state")
        logger.debug("x_sentiment: no metrics, emitting NEUTRAL")
        _signals_total.labels(bias="NEUTRAL", path="gate_bypass").inc()
        return {"x_sentiment_signal": signal, "signals": [_metrics_to_agent_signal(signal)]}

    logger.info(
        "x_sentiment: volume_spike_ratio=%.2f impact=%.3f samples=%d",
        metrics.volume_spike_ratio, metrics.impact_score,
        len(metrics.high_impact_text_samples),
    )

    # --- volume gate ---
    if metrics.volume_spike_ratio < VOLUME_GATE_THRESHOLD:
        signal = _make_neutral(
            f"volume_spike_ratio {metrics.volume_spike_ratio:.2f} < {VOLUME_GATE_THRESHOLD}",
            metrics.source_tweet_ids,
        )
        logger.debug("x_sentiment: gate bypass (ratio=%.2f)", metrics.volume_spike_ratio)
        _signals_total.labels(bias="NEUTRAL", path="gate_bypass").inc()
        return {"x_sentiment_signal": signal, "signals": [_metrics_to_agent_signal(signal)]}

    # --- LLM path ---
    t0 = time.perf_counter()
    try:
        signal = _run_async_with_timeout(metrics)
        elapsed = time.perf_counter() - t0
        _llm_latency.observe(elapsed)
        _signals_total.labels(bias=signal.sentiment_bias, path="llm").inc()
        logger.info(
            "x_sentiment: LLM result bias=%s conviction=%.2f vol_alert=%s latency=%.3fs",
            signal.sentiment_bias, signal.conviction_score, signal.volatility_alert, elapsed,
        )
    except asyncio.TimeoutError:
        _timeout_total.inc()
        signal = _make_neutral("llm timeout (3s)", metrics.source_tweet_ids)
        logger.warning("x_sentiment: LLM timed out after 3s, falling back to NEUTRAL")
        _signals_total.labels(bias="NEUTRAL", path="gate_bypass").inc()
    except Exception as exc:
        signal = _make_neutral(f"llm error: {type(exc).__name__}", metrics.source_tweet_ids)
        logger.error("x_sentiment: LLM error: %s", exc, exc_info=True)
        _signals_total.labels(bias="NEUTRAL", path="gate_bypass").inc()

    return {"x_sentiment_signal": signal, "signals": [_metrics_to_agent_signal(signal)]}


def _run_async_with_timeout(metrics: XSentimentMetrics) -> XSentimentSignal:
    """Run the async LLM call from a sync context with a hard timeout."""
    async def _inner() -> XSentimentSignal:
        return await asyncio.wait_for(_invoke_llm(metrics), timeout=LLM_TIMEOUT_SECONDS)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already inside an async context (e.g. async LangGraph)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(asyncio.run, _inner())
                return future.result(timeout=LLM_TIMEOUT_SECONDS + 1.0)
        else:
            return loop.run_until_complete(_inner())
    except RuntimeError:
        return asyncio.run(_inner())


# --------------------------------------------------------------------------- #
# Bridge: XSentimentSignal → AgentSignal so orchestrator consensus tally works
# --------------------------------------------------------------------------- #
def _metrics_to_agent_signal(signal: XSentimentSignal):
    from core.enums import AgentVote
    from core.schemas import AgentSignal

    vote_map = {"BULLISH": AgentVote.LONG, "BEARISH": AgentVote.SHORT, "NEUTRAL": AgentVote.ABSTAIN}
    return AgentSignal(
        agent_name="x_sentiment",
        vote=vote_map.get(signal.sentiment_bias, AgentVote.ABSTAIN),
        confidence=signal.conviction_score,
        rationale=signal.primary_catalyst_summary[:300],
    )
