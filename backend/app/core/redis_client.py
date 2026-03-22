"""
app/core/redis_client.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Async Redis Bus & Distributed Locker
──────────────────────────────────────────────────────────────────────────────

Wraps redis.asyncio with three concerns:

  1. Connection pool management  — single pool per process, lazy-initialised.
  2. Distributed locking         — SETNX-based per-flight booking guards.
  3. Pub/Sub bus                 — JSON publish for events + raw pubsub handle
                                   returned to game_loop and live_ops.

Public API consumed by other modules
──────────────────────────────────────
  booking.py   →  acquire_lock / release_lock / publish
  game_loop.py →  create_pubsub / publish
  live_ops.py  →  create_pubsub
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

from app.core.config import settings

logger = logging.getLogger("orchestrator.redis")

# ---------------------------------------------------------------------------
# Module-level connection pool — created once, shared across all coroutines.
# redis.asyncio.ConnectionPool is thread-safe and asyncio-safe.
# ---------------------------------------------------------------------------
_redis_pool: aioredis.ConnectionPool | None = None


def _get_pool() -> aioredis.ConnectionPool:
    """
    Lazily initialise the global connection pool from REDIS_URI.

    Using a pool (rather than a single connection) allows concurrent
    booking requests to each grab their own connection without blocking.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URI,
            decode_responses=True,
            max_connections=200,   # scaled for 500-agent swarm (was 20)
        )
        logger.info("Redis connection pool initialised → %s", settings.REDIS_URI)
    return _redis_pool


def _get_client() -> aioredis.Redis:
    """Return a Redis client that borrows a connection from the shared pool."""
    return aioredis.Redis(connection_pool=_get_pool())


# ---------------------------------------------------------------------------
# Distributed lock helpers
# ---------------------------------------------------------------------------

async def acquire_lock(lock_key: str, ttl: int) -> bool:
    """
    Attempt to acquire a SETNX-based distributed lock.

    Args:
        lock_key : Redis key, e.g. ``"lock:booking:6E-101_A_2026-10-16"``.
        ttl      : Lock expiry in seconds (from ``settings.REDIS_LOCK_TTL_SECONDS``).

    Returns:
        ``True``  — lock acquired; caller may proceed with the critical section.
        ``False`` — lock already held by another coroutine/process; caller
                    should raise HTTP 409 and ask the client to retry.

    Implementation note:
        ``SET key value NX EX ttl`` is atomic and avoids the classic
        SETNX + EXPIRE race condition present in older Redis clients.
    """
    client = _get_client()
    try:
        result = await client.set(
            name=lock_key,
            value="1",
            nx=True,         # SET only if Not eXists
            ex=ttl,          # auto-expire so a crashed holder never blocks forever
        )
        acquired = result is True
        if not acquired:
            logger.debug("Lock contention: key=%s already held", lock_key)
        return acquired
    finally:
        await client.aclose()


async def release_lock(lock_key: str) -> None:
    """
    Unconditionally delete the lock key.

    Called in a ``finally`` block inside booking.py so the lock is always
    released even when an exception propagates.  Swallows errors so a Redis
    hiccup on teardown never masks the original exception.
    """
    client = _get_client()
    try:
        await client.delete(lock_key)
        logger.debug("Lock released: key=%s", lock_key)
    except Exception as exc:
        logger.warning("Failed to release lock %s: %s", lock_key, exc)
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Pub/Sub publisher
# ---------------------------------------------------------------------------

async def publish(channel: str, message: dict[str, Any]) -> None:
    """
    Serialise *message* to JSON and publish it to *channel*.

    Args:
        channel : Redis Pub/Sub channel name (e.g. ``settings.REDIS_BROADCAST_CHANNEL``).
        message : Python dict; must be JSON-serialisable.

    Raises:
        TypeError   : If *message* contains non-serialisable values.
        redis.RedisError : On connection failures (propagated to caller).
    """
    client = _get_client()
    try:
        payload = json.dumps(message, default=str)
        subscriber_count = await client.publish(channel, payload)
        logger.debug(
            "Published event_type=%s to channel=%s (%d subscriber(s))",
            message.get("event_type", "UNKNOWN"),
            channel,
            subscriber_count,
        )
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Pub/Sub subscriber factory
# ---------------------------------------------------------------------------

async def create_pubsub() -> PubSub:
    """
    Create and return a new ``redis.asyncio.client.PubSub`` object.

    The caller is responsible for:
      1. Calling ``await pubsub.subscribe(channel)`` after receiving the object.
      2. Iterating with ``async for msg in pubsub.listen()``.
      3. Calling ``await pubsub.unsubscribe(channel)`` and
         ``await pubsub.aclose()`` in a ``finally`` block.

    Each call creates a **dedicated** connection for the subscription so that
    blocking ``listen()`` never starves the shared pool used by lock/publish.

    Returns:
        A fresh :class:`redis.asyncio.client.PubSub` instance.
    """
    client = aioredis.Redis.from_url(
        settings.REDIS_URI,
        decode_responses=True,
    )
    pubsub = client.pubsub()
    logger.debug("New PubSub connection created")
    return pubsub
