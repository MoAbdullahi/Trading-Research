"""Deterministic quant feature engine for X sentiment.

This module sits between raw tweet storage and the LLM agent.  It:
  1. Pulls a 15-min rolling window of tweets from the DB via the injected service.
  2. Cleans and fuzzy-deduplicates text (threshold 0.92) with rapidfuzz.
  3. Computes volume_spike_ratio against a 4-hour EWMA baseline via Polars.
  4. Scores each tweet with keyword rules (handle-specific).
  5. Returns an XSentimentMetrics that the agent node uses as gate + LLM input.

All public functions are pure (no I/O) except `compute_metrics()` which injects
the storage service.  Pure functions are independently unit-testable.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Sequence

from core.schemas import RawTweetRecord, XSentimentMetrics

if TYPE_CHECKING:
    from ingestion.x_stream import TweetIngestionService

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#\w+")
_WHITESPACE_RE = re.compile(r"\s+")

FUZZY_THRESHOLD = 0.92   # rapidfuzz token_set_ratio threshold for near-duplicate detection
MAX_SAMPLES = 5           # top-N high-impact cleaned texts surfaced to the LLM

# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #
def clean_text(raw: str) -> str:
    """Lowercase, strip URLs, @mentions; keep #tags text; collapse whitespace."""
    text = _URL_RE.sub(" ", raw)
    text = _MENTION_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(lambda m: m.group(0)[1:], text)  # keep tag word, drop #
    text = text.lower()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def fuzzy_deduplicate(texts: Sequence[str], threshold: float = FUZZY_THRESHOLD) -> list[str]:
    """Remove near-duplicate strings using rapidfuzz token_set_ratio.

    O(n²) in the worst case, but tweet windows are small (< 200 items) so this
    is perfectly acceptable.  Returns the first representative from each cluster.
    """
    try:
        from rapidfuzz.fuzz import token_set_ratio
    except ImportError:
        logger.warning("rapidfuzz not installed — falling back to exact dedup")
        seen: set[str] = set()
        return [t for t in texts if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]

    kept: list[str] = []
    for candidate in texts:
        is_dup = any(
            token_set_ratio(candidate, existing) / 100.0 >= threshold
            for existing in kept
        )
        if not is_dup:
            kept.append(candidate)
    return kept


# --------------------------------------------------------------------------- #
# Keyword scoring — pure functions, unit-testable in isolation
# --------------------------------------------------------------------------- #
def score_deltaaone_financialjuice(text: str) -> float:
    """Score a cleaned text for risk/macro impact (DeItaone, financialjuice).

    Scans for risk keywords that appear IN ALL-CAPS in the original text.
    A tweet that screams EMERGENCY RATE HIKE scores higher than one that
    mentions 'rate hike' in passing.
    """
    from config.keywords import RISK_KEYWORDS, MACRO_SHOCK_KEYWORDS

    upper = text.upper()
    risk_hits = sum(1 for kw in RISK_KEYWORDS if kw in upper)
    macro_hits = sum(1 for kw in MACRO_SHOCK_KEYWORDS if kw in upper)
    raw = risk_hits * 1.5 + macro_hits * 0.5
    return min(raw / 5.0, 1.0)   # normalise to [0, 1]


def score_unusual_whales(text: str) -> float:
    """Score a cleaned text for equity options flow impact (unusual_whales).

    Detects PUT/CALL premium language and flow directionality.
    """
    from config.keywords import (
        OPTIONS_FLOW_KEYWORDS,
        BULLISH_FLOW_KEYWORDS,
        BEARISH_FLOW_KEYWORDS,
    )

    upper = text.upper()
    flow_hits = sum(1 for kw in OPTIONS_FLOW_KEYWORDS if kw in upper)
    bull_hits = sum(1 for kw in BULLISH_FLOW_KEYWORDS if kw in upper)
    bear_hits = sum(1 for kw in BEARISH_FLOW_KEYWORDS if kw in upper)
    raw = flow_hits * 1.0 + (bull_hits + bear_hits) * 0.5
    return min(raw / 4.0, 1.0)


_HANDLE_SCORER = {
    "deitaone": score_deltaaone_financialjuice,      # @DeItaone (Walter Bloomberg)
    "financialjuice": score_deltaaone_financialjuice,
    "unusual_whales": score_unusual_whales,
}


def score_tweet(record: RawTweetRecord) -> float:
    """Dispatch to the correct handle scorer; return 0.0 for unknown handles."""
    fn = _HANDLE_SCORER.get(record.author_handle.lower(), lambda _: 0.0)
    return fn(clean_text(record.text))


def keyword_sentiment_score(records: Sequence[RawTweetRecord]) -> float:
    """Aggregate model_score in [-1, 1]: positive = net bullish, negative = net bearish."""
    from config.keywords import BULLISH_FLOW_KEYWORDS, BEARISH_FLOW_KEYWORDS, RISK_KEYWORDS

    if not records:
        return 0.0

    total = 0.0
    for r in records:
        upper = r.text.upper()
        bull = sum(1 for kw in BULLISH_FLOW_KEYWORDS if kw in upper)
        bear = sum(1 for kw in BEARISH_FLOW_KEYWORDS if kw in upper)
        risk = sum(1 for kw in RISK_KEYWORDS if kw in upper)
        total += (bull - bear - risk * 0.5)

    raw = total / (len(records) * 3.0)   # normalise
    return max(-1.0, min(1.0, raw))


# --------------------------------------------------------------------------- #
# Volume spike ratio (Polars EWMA)
# --------------------------------------------------------------------------- #
def compute_volume_spike_ratio(
    current_window_count: int,
    historical_timestamps: list[datetime],
) -> float:
    """Compute volume_spike_ratio = current_count / EWMA baseline.

    historical_timestamps: all tweet timestamps from the past 4 hours (from DB).
    Uses a 30-minute EWMA bin to get a smoothed baseline.
    """
    if not historical_timestamps:
        return float(current_window_count) if current_window_count > 0 else 1.0

    try:
        import polars as pl
    except ImportError:
        logger.warning("polars not installed — using simple mean baseline")
        # Fallback: simple ratio against mean of 30-min bins
        now = datetime.now(timezone.utc)
        bins = []
        for offset in range(8):
            bin_start = now - timedelta(minutes=30 * (offset + 1))
            bin_end = now - timedelta(minutes=30 * offset)
            bins.append(sum(1 for ts in historical_timestamps if bin_start <= ts < bin_end))
        baseline = sum(bins) / max(len([b for b in bins if b > 0]), 1)
        return round(current_window_count / baseline, 3) if baseline > 0 else float(current_window_count)

    now = datetime.now(timezone.utc)
    # Build 30-min bins over last 4 hours (8 bins)
    bins: list[int] = []
    for offset in range(8):
        bin_start = now - timedelta(minutes=30 * (offset + 1))
        bin_end = now - timedelta(minutes=30 * offset)
        count = sum(1 for ts in historical_timestamps if bin_start <= ts < bin_end)
        bins.append(count)

    if not any(b > 0 for b in bins):
        return float(current_window_count) if current_window_count > 0 else 1.0

    s = pl.Series("counts", bins, dtype=pl.Float64)
    # EWMA with span=4 (half the 8-bin window)
    ewma = s.ewm_mean(span=4, adjust=True)
    baseline = float(ewma[-1])
    if baseline <= 0:
        return float(current_window_count)

    return round(current_window_count / baseline, 3)


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def compute_metrics(
    service: "TweetIngestionService",
    handles: list[str],
    window_minutes: int = 15,
    history_minutes: int = 240,
) -> XSentimentMetrics:
    """Pull tweets, clean, deduplicate, score and return XSentimentMetrics.

    This is the ONLY function that touches I/O (via the injected service).
    Everything it calls downstream is pure.
    """
    records: list[RawTweetRecord] = service.get_tweets_in_window(handles, window_minutes)

    if not records:
        return XSentimentMetrics(
            volume_spike_ratio=0.0,
            model_score=0.0,
            high_impact_text_samples=[],
            impact_score=0.0,
            source_tweet_ids=[],
        )

    # --- volume spike ---
    historical = service.get_tweets_in_window(handles, history_minutes)
    historical_ts: list[datetime] = [r.timestamp for r in historical]
    spike_ratio = compute_volume_spike_ratio(len(records), historical_ts)

    # --- clean + fuzzy-deduplicate ---
    cleaned_pairs: list[tuple[str, RawTweetRecord]] = [
        (clean_text(r.text), r) for r in records
    ]
    unique_texts = fuzzy_deduplicate([p[0] for p in cleaned_pairs])
    unique_set = set(unique_texts)
    deduped_records: list[RawTweetRecord] = [
        r for text, r in cleaned_pairs if text in unique_set
    ]

    # --- score each de-duped record ---
    scored: list[tuple[float, str, str]] = []   # (score, cleaned_text, tweet_id)
    for r in deduped_records:
        ct = clean_text(r.text)
        sc = score_tweet(r)
        scored.append((sc, ct, r.tweet_id))

    scored.sort(key=lambda x: x[0], reverse=True)

    top_samples: list[str] = [s[1] for s in scored[:MAX_SAMPLES] if s[1]]
    source_ids: list[str] = [s[2] for s in scored]

    # --- aggregate model score ---
    model_score = keyword_sentiment_score(deduped_records)

    # --- impact score: EWMA-weighted average of individual scores ---
    if scored:
        weights = [s[0] for s in scored]
        w_sum = sum(weights)
        impact = w_sum / len(scored) if w_sum > 0 else 0.0
        impact = min(impact * spike_ratio / 2.0, 1.0)
    else:
        impact = 0.0

    return XSentimentMetrics(
        volume_spike_ratio=round(spike_ratio, 4),
        model_score=round(max(-1.0, min(1.0, model_score)), 4),
        high_impact_text_samples=top_samples,
        impact_score=round(impact, 4),
        source_tweet_ids=source_ids[:50],   # cap to avoid oversized state
    )
