"""Ingestion layer — X (Twitter) stream via twscrape.

Design rules enforced here:
 - Deduplication by tweet_id at ingress (Postgres unique constraint + in-memory set).
 - Append-only writes: raw_tweets is never UPDATE'd, only INSERT'd.
 - All retry logic wraps the I/O boundary; business logic above is never retried.
 - Account pool rotates on rate-limit (429) to maximise sustainable throughput.
 - The LLM lane never touches this module; it reads only through get_tweets_in_window().
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, List, Optional

from core.schemas import RawTweetRecord

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Retry decorator — exponential backoff, max 5 attempts
# --------------------------------------------------------------------------- #
def _retry(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s", fn.__name__, max_attempts, exc
                        )
                        raise
                    jitter = delay * 0.1
                    sleep_for = min(delay + jitter, max_delay)
                    logger.warning(
                        "%s attempt %d/%d failed (%s). Retrying in %.1fs.",
                        fn.__name__, attempt, max_attempts, exc, sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    delay = min(delay * 2, max_delay)

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s", fn.__name__, max_attempts, exc
                        )
                        raise
                    sleep_for = min(delay, max_delay)
                    logger.warning(
                        "%s attempt %d/%d failed (%s). Retrying in %.1fs.",
                        fn.__name__, attempt, max_attempts, exc, sleep_for,
                    )
                    time.sleep(sleep_for)
                    delay = min(delay * 2, max_delay)

        return async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper
    return decorator


# --------------------------------------------------------------------------- #
# Postgres DDL (executed on service start via the injected engine)
# --------------------------------------------------------------------------- #
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS raw_tweets (
    id            BIGSERIAL    PRIMARY KEY,
    tweet_id      TEXT         NOT NULL UNIQUE,
    author_handle TEXT         NOT NULL,
    text          TEXT         NOT NULL,
    ts            TIMESTAMPTZ  NOT NULL,
    is_all_caps   BOOLEAN      NOT NULL DEFAULT FALSE,
    contains_market_flow BOOLEAN NOT NULL DEFAULT FALSE,
    ingested_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_raw_tweets_ts            ON raw_tweets (ts DESC);
CREATE INDEX IF NOT EXISTS idx_raw_tweets_author_handle ON raw_tweets (author_handle, ts DESC);
"""

# --------------------------------------------------------------------------- #
# TweetIngestionService
# --------------------------------------------------------------------------- #
class TweetIngestionService:
    """Manages the full tweet lifecycle: scrape → deduplicate → persist → expose.

    Dependency-injected DB client keeps the service independently testable.  The
    `db` parameter accepts any object with:
      - execute(sql, params)       — for DDL + DML
      - fetchall(sql, params)      — for SELECT queries
      - commit()                   — to flush writes

    In production pass a SQLAlchemy Connection or psycopg connection.  In tests
    pass a lightweight stub (see tests/test_sentiment_engine.py).
    """

    def __init__(self, db: Any, accounts: Optional[list[dict]] = None) -> None:
        self._db = db
        self._accounts = accounts or []
        self._seen_ids: set[str] = set()   # in-process dedup guard; Postgres is authoritative
        self._scraper: Any = None           # twscrape.API instance, lazy-init

        self._ensure_schema()
        self._seed_seen_ids()

    # --------------------------------------------------------------------- #
    # Schema bootstrap
    # --------------------------------------------------------------------- #
    def _ensure_schema(self) -> None:
        try:
            self._db.execute(_CREATE_TABLE_SQL)
            self._db.commit()
            logger.info("raw_tweets schema ensured")
        except Exception as exc:
            logger.warning("schema init warning (may already exist): %s", exc)

    def _seed_seen_ids(self) -> None:
        """Warm the in-memory dedupe set from recent DB rows on startup."""
        try:
            rows = self._db.fetchall(
                "SELECT tweet_id FROM raw_tweets WHERE ingested_at > NOW() - INTERVAL '24 hours'"
            )
            self._seen_ids = {r[0] for r in rows}
            logger.info("dedup set seeded with %d recent tweet IDs", len(self._seen_ids))
        except Exception as exc:
            logger.warning("could not seed seen_ids: %s", exc)

    # --------------------------------------------------------------------- #
    # Scraper bootstrap (lazy — so tests never touch twscrape)
    # --------------------------------------------------------------------- #
    async def _get_scraper(self):
        if self._scraper is not None:
            return self._scraper
        try:
            from twscrape import API, gather  # noqa: F401
            self._scraper = API()
            for acct in self._accounts:
                await self._scraper.pool.add_account(**acct)
            await self._scraper.pool.login_all()
            logger.info("twscrape pool initialised with %d accounts", len(self._accounts))
        except ImportError:
            logger.warning("twscrape not installed — ingestion disabled")
            self._scraper = None
        except Exception as exc:
            logger.error("twscrape pool init failed: %s", exc)
            self._scraper = None
        return self._scraper

    # --------------------------------------------------------------------- #
    # Core ingestion worker
    # --------------------------------------------------------------------- #
    @_retry(max_attempts=5, base_delay=2.0, exceptions=(Exception,))
    async def _ingest_handle(self, handle: str, limit: int = 50) -> int:
        api = await self._get_scraper()
        if api is None:
            return 0

        from twscrape import gather
        tweets = await gather(api.user_tweets(handle, limit=limit))
        inserted = 0
        for tw in tweets:
            if tw.id_str in self._seen_ids:
                continue
            record = _tweet_to_record(tw)
            self._persist(record)
            self._seen_ids.add(tw.id_str)
            inserted += 1
        logger.debug("handle=%s new_tweets=%d", handle, inserted)
        return inserted

    def _persist(self, record: RawTweetRecord) -> None:
        sql = """
            INSERT INTO raw_tweets (tweet_id, author_handle, text, ts, is_all_caps, contains_market_flow)
            VALUES (:tweet_id, :author_handle, :text, :ts, :is_all_caps, :contains_market_flow)
            ON CONFLICT (tweet_id) DO NOTHING
        """
        self._db.execute(sql, record.model_dump())
        self._db.commit()

    # --------------------------------------------------------------------- #
    # Public query surface (synchronous, used by the feature engine)
    # --------------------------------------------------------------------- #
    def get_tweets_in_window(
        self, handle_list: List[str], minutes: int = 15
    ) -> List[RawTweetRecord]:
        """Return all stored tweets from `handle_list` in the last `minutes` window."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        placeholders = ",".join(f":h{i}" for i in range(len(handle_list)))
        params: dict = {f"h{i}": h for i, h in enumerate(handle_list)}
        params["cutoff"] = cutoff
        sql = f"""
            SELECT tweet_id, author_handle, text, ts, is_all_caps, contains_market_flow
            FROM   raw_tweets
            WHERE  author_handle IN ({placeholders})
              AND  ts >= :cutoff
            ORDER BY ts DESC
        """
        rows = self._db.fetchall(sql, params)
        return [
            RawTweetRecord(
                tweet_id=r[0],
                author_handle=r[1],
                text=r[2],
                timestamp=r[3] if isinstance(r[3], datetime) else datetime.fromisoformat(str(r[3])),
                is_all_caps=bool(r[4]),
                contains_market_flow=bool(r[5]),
            )
            for r in rows
        ]

    # --------------------------------------------------------------------- #
    # Run loop — call from asyncio.run() in your main entrypoint
    # --------------------------------------------------------------------- #
    async def run_forever(self, handles: List[str], poll_interval_seconds: float = 60.0) -> None:
        logger.info("ingestion loop started for handles: %s", handles)
        while True:
            for handle in handles:
                try:
                    await self._ingest_handle(handle)
                except Exception as exc:
                    logger.error("ingestion failed for @%s: %s", handle, exc)
            await asyncio.sleep(poll_interval_seconds)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _is_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.8


def _contains_market_flow(text: str) -> bool:
    from config.keywords import OPTIONS_FLOW_KEYWORDS, BULLISH_FLOW_KEYWORDS, BEARISH_FLOW_KEYWORDS
    upper = text.upper()
    return any(kw in upper for kw in OPTIONS_FLOW_KEYWORDS | BULLISH_FLOW_KEYWORDS | BEARISH_FLOW_KEYWORDS)


def _tweet_to_record(tw: Any) -> RawTweetRecord:
    text = getattr(tw, "rawContent", None) or getattr(tw, "full_text", "") or ""
    return RawTweetRecord(
        tweet_id=str(tw.id_str),
        author_handle=str(getattr(tw, "user", {}).username if hasattr(tw, "user") else ""),
        text=text,
        timestamp=tw.date.replace(tzinfo=timezone.utc) if tw.date.tzinfo is None else tw.date,
        is_all_caps=_is_all_caps(text),
        contains_market_flow=_contains_market_flow(text),
    )
