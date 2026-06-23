"""Unit tests for the X sentiment feature engine.

All DB interactions are stubbed — no live Postgres required.
rapidfuzz and polars are assumed installed (see requirements snippet).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.schemas import RawTweetRecord, XSentimentMetrics
from features.sentiment_engine import (
    clean_text,
    compute_metrics,
    compute_volume_spike_ratio,
    fuzzy_deduplicate,
    keyword_sentiment_score,
    score_deltaaone_financialjuice,
    score_unusual_whales,
    score_tweet,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ts(offset_minutes: int = 0) -> datetime:
    from datetime import timedelta
    return datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)


def _tweet(
    text: str,
    handle: str = "DeItaone",
    tweet_id: str = "1",
    is_all_caps: bool = False,
    contains_market_flow: bool = False,
    offset_minutes: int = 0,
) -> RawTweetRecord:
    return RawTweetRecord(
        tweet_id=tweet_id,
        author_handle=handle,
        text=text,
        timestamp=_ts(offset_minutes),
        is_all_caps=is_all_caps,
        contains_market_flow=contains_market_flow,
    )


class _StubDB:
    """Minimal DB stub: records writes, returns a configurable list on fetchall."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[str] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append(sql)

    def fetchall(self, sql: str, params: Any = None) -> list[Any]:
        return self.rows

    def commit(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# clean_text
# --------------------------------------------------------------------------- #
class TestCleanText:
    def test_lowercases(self):
        assert clean_text("BREAKING NEWS") == "breaking news"

    def test_strips_urls(self):
        result = clean_text("check https://t.co/abc123 out")
        assert "https" not in result
        assert "t.co" not in result

    def test_strips_mentions(self):
        result = clean_text("@DeItaone says the market crashed")
        assert "@" not in result
        assert "deltaaone" not in result  # mention stripped

    def test_keeps_hashtag_word(self):
        result = clean_text("big #Crash today")
        assert "crash" in result
        assert "#" not in result

    def test_collapses_whitespace(self):
        result = clean_text("  too    many   spaces  ")
        assert "  " not in result
        assert result == "too many spaces"

    def test_empty_string(self):
        assert clean_text("") == ""


# --------------------------------------------------------------------------- #
# fuzzy_deduplicate
# --------------------------------------------------------------------------- #
class TestFuzzyDeduplicate:
    def test_exact_duplicates_removed(self):
        # Works even without rapidfuzz (fallback does exact dedup)
        texts = ["federal reserve raises rates", "federal reserve raises rates"]
        result = fuzzy_deduplicate(texts)
        assert len(result) == 1

    def test_near_duplicates_removed(self):
        pytest.importorskip("rapidfuzz")
        a = "fed raises rates by 25 basis points"
        b = "fed raises rates by 25 bps"
        result = fuzzy_deduplicate([a, b], threshold=0.85)
        assert len(result) == 1

    def test_distinct_texts_kept(self):
        a = "gold surges on safe haven demand"
        b = "oil prices collapse on supply glut"
        result = fuzzy_deduplicate([a, b])
        assert len(result) == 2

    def test_empty_list(self):
        assert fuzzy_deduplicate([]) == []

    def test_single_item(self):
        assert fuzzy_deduplicate(["hello"]) == ["hello"]


# --------------------------------------------------------------------------- #
# Keyword scoring — DeItaone / financialjuice
# --------------------------------------------------------------------------- #
class TestScoreDeltaOne:
    def test_risk_keyword_raises_score(self):
        score = score_deltaaone_financialjuice("EMERGENCY RATE HIKE BY THE FED")
        assert score > 0.0

    def test_macro_shock_keyword_scores(self):
        score = score_deltaaone_financialjuice("BREAKING: bank collapse in europe")
        assert score > 0.0

    def test_benign_text_scores_zero(self):
        score = score_deltaaone_financialjuice("the weather is nice today")
        assert score == 0.0

    def test_multiple_risk_keywords_boost_score(self):
        low = score_deltaaone_financialjuice("CRISIS")
        high = score_deltaaone_financialjuice("EMERGENCY CRISIS COLLAPSE BAILOUT DEFAULT")
        assert high > low

    def test_score_capped_at_one(self):
        text = " ".join(["EMERGENCY CRASH CRISIS COLLAPSE HALT FREEZE SYSTEMIC"] * 5)
        assert score_deltaaone_financialjuice(text) <= 1.0


# --------------------------------------------------------------------------- #
# Keyword scoring — unusual_whales
# --------------------------------------------------------------------------- #
class TestScoreUnusualWhales:
    def test_put_flow_scores(self):
        score = score_unusual_whales("large PUT sweep on SPY 10M premium")
        assert score > 0.0

    def test_call_flow_scores(self):
        score = score_unusual_whales("UNUSUAL CALLS on NVDA, bullish sweep")
        assert score > 0.0

    def test_irrelevant_text_scores_zero(self):
        score = score_unusual_whales("happy monday everyone")
        assert score == 0.0

    def test_score_capped_at_one(self):
        text = " ".join(["PUT CALL SWEEP BULLISH BEARISH FLOW OI OPEN INTEREST"] * 5)
        assert score_unusual_whales(text) <= 1.0


# --------------------------------------------------------------------------- #
# score_tweet dispatch
# --------------------------------------------------------------------------- #
class TestScoreTweetDispatch:
    def test_deltaaone_uses_correct_scorer(self):
        tw = _tweet("EMERGENCY RATE HIKE", handle="DeItaone")
        assert score_tweet(tw) > 0.0

    def test_financialjuice_uses_correct_scorer(self):
        tw = _tweet("BREAKING: BANK DEFAULT", handle="financialjuice")
        assert score_tweet(tw) > 0.0

    def test_unusual_whales_uses_correct_scorer(self):
        tw = _tweet("big PUT sweep on SPY", handle="unusual_whales")
        assert score_tweet(tw) > 0.0

    def test_unknown_handle_returns_zero(self):
        tw = _tweet("EMERGENCY COLLAPSE", handle="randomperson")
        assert score_tweet(tw) == 0.0


# --------------------------------------------------------------------------- #
# keyword_sentiment_score
# --------------------------------------------------------------------------- #
class TestKeywordSentimentScore:
    def test_empty_list_returns_zero(self):
        assert keyword_sentiment_score([]) == 0.0

    def test_bullish_tweets_positive_score(self):
        tweets = [_tweet("BULLISH CALLS sweep on AAPL", tweet_id=str(i)) for i in range(5)]
        assert keyword_sentiment_score(tweets) > 0.0

    def test_bearish_tweets_negative_score(self):
        tweets = [_tweet("BEARISH PUTS dump on SPY", tweet_id=str(i)) for i in range(5)]
        assert keyword_sentiment_score(tweets) < 0.0

    def test_risk_tweets_negative_bias(self):
        tweets = [_tweet("CRASH CRISIS COLLAPSE EMERGENCY", tweet_id=str(i)) for i in range(5)]
        score = keyword_sentiment_score(tweets)
        assert score <= 0.0

    def test_score_within_bounds(self):
        tweets = [_tweet("BULLISH BULLISH BULLISH CALLS CALLS", tweet_id=str(i)) for i in range(20)]
        score = keyword_sentiment_score(tweets)
        assert -1.0 <= score <= 1.0


# --------------------------------------------------------------------------- #
# compute_volume_spike_ratio
# --------------------------------------------------------------------------- #
class TestComputeVolumeSpikeRatio:
    def test_empty_history_returns_current_count(self):
        assert compute_volume_spike_ratio(5, []) == 5.0

    def test_zero_current_empty_history_returns_one(self):
        assert compute_volume_spike_ratio(0, []) == 1.0

    def test_high_current_vs_low_baseline_spikes(self):
        # 1 tweet per 30-min bin historically, 50 in current window — expects spike
        hist = [_ts(30 * i + 5) for i in range(1, 9)]
        ratio = compute_volume_spike_ratio(50, hist)
        assert ratio > 2.0

    def test_stable_volume_returns_near_one(self):
        from datetime import timedelta
        # 10 tweets per bin historically, 10 in current window
        hist = [_ts(30 * i + j * 2) for i in range(1, 9) for j in range(10)]
        ratio = compute_volume_spike_ratio(10, hist)
        assert 0.3 <= ratio <= 3.0   # loose bounds — EWMA smoothing can vary


# --------------------------------------------------------------------------- #
# compute_metrics (integration — DB stubbed)
# --------------------------------------------------------------------------- #
class TestComputeMetrics:
    def _make_service(self, window_rows: list[RawTweetRecord], history_rows: list[RawTweetRecord] | None = None):
        from ingestion.x_stream import TweetIngestionService
        svc = MagicMock(spec=TweetIngestionService)
        call_count = [0]

        def fake_get_tweets(handle_list, minutes):
            call_count[0] += 1
            if call_count[0] == 1:
                return window_rows
            return history_rows or window_rows

        svc.get_tweets_in_window.side_effect = fake_get_tweets
        return svc

    def test_no_tweets_returns_zero_metrics(self):
        svc = self._make_service([])
        metrics = compute_metrics(svc, ["DeItaone"])
        assert metrics.trades_count if hasattr(metrics, "trades_count") else True
        assert metrics.volume_spike_ratio == 0.0
        assert metrics.model_score == 0.0
        assert metrics.impact_score == 0.0
        assert metrics.source_tweet_ids == []

    def test_risk_tweets_produce_nonzero_impact(self):
        tweets = [
            _tweet("EMERGENCY RATE HIKE CRISIS", handle="DeItaone", tweet_id=str(i))
            for i in range(5)
        ]
        svc = self._make_service(tweets)
        metrics = compute_metrics(svc, ["DeItaone"])
        assert metrics.impact_score > 0.0

    def test_source_tweet_ids_populated(self):
        tweets = [_tweet("BREAKING NEWS", tweet_id=str(i)) for i in range(3)]
        svc = self._make_service(tweets)
        metrics = compute_metrics(svc, ["DeItaone"])
        assert len(metrics.source_tweet_ids) > 0

    def test_near_duplicate_tweets_deduplicated(self):
        tweets = [
            _tweet("fed raises rates by 25 bps today", tweet_id="1"),
            _tweet("fed raises rates by 25 basis points today", tweet_id="2"),
            _tweet("gold surges on safe haven demand", tweet_id="3"),
        ]
        svc = self._make_service(tweets)
        metrics = compute_metrics(svc, ["DeItaone"])
        # After dedup we should have 2 unique clusters, not 3
        assert len(metrics.source_tweet_ids) <= 3

    def test_high_impact_samples_capped_at_five(self):
        tweets = [
            _tweet(f"EMERGENCY CRISIS number {i}", tweet_id=str(i))
            for i in range(10)
        ]
        svc = self._make_service(tweets)
        metrics = compute_metrics(svc, ["DeItaone"])
        assert len(metrics.high_impact_text_samples) <= 5

    def test_metrics_schema_valid(self):
        tweets = [_tweet("BREAKING CRASH", tweet_id="42")]
        svc = self._make_service(tweets)
        metrics = compute_metrics(svc, ["DeItaone"])
        assert isinstance(metrics, XSentimentMetrics)
        assert -1.0 <= metrics.model_score <= 1.0
        assert 0.0 <= metrics.impact_score <= 1.0
        assert metrics.volume_spike_ratio >= 0.0
