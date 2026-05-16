from __future__ import annotations

import hashlib
from collections.abc import Callable, Coroutine
from typing import Any

import msgpack
import redis.asyncio as aioredis


class RedisCache:
    def __init__(self, redis: aioredis.Redis, ttl: int) -> None:  # type: ignore[type-arg]
        self._redis = redis
        self._ttl = ttl

    async def get_or_set_embedding(
        self,
        query: str,
        factory: Callable[[], Coroutine[Any, Any, list[float]]],
    ) -> list[float]:
        key = f"emb:{hashlib.sha256(query.encode()).hexdigest()}"
        cached = await self._redis.get(key)
        if cached is not None:
            result: list[float] = msgpack.unpackb(cached)
            return result
        vector = await factory()
        await self._redis.set(key, msgpack.packb(vector), ex=self._ttl)
        return vector
