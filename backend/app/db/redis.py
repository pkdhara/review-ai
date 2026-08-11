"""Redis client and pub/sub helper for SSE progress streaming."""
import json
from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        log.info("redis.connection_closed")


async def publish_progress(review_id: str, payload: dict) -> None:
    """Publish a progress event to Redis pub/sub channel."""
    r = await get_redis()
    channel = f"review:{review_id}:progress"
    await r.publish(channel, json.dumps(payload))


async def stream_progress(review_id: str) -> AsyncGenerator[str, None]:
    """Subscribe to progress channel and yield SSE-formatted messages."""
    r = await get_redis()
    pubsub = r.pubsub()
    channel = f"review:{review_id}:progress"
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                yield f"data: {data}\n\n"
                # Stop streaming when review is terminal
                try:
                    payload = json.loads(data)
                    if payload.get("status") in ("completed", "failed", "cancelled"):
                        break
                except json.JSONDecodeError:
                    pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
