from __future__ import annotations

import time
from typing import Annotated

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Response, status
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from search_service.config import Settings, get_settings
from search_service.db.session import get_session_maker
from search_service.deps import get_embedder, get_qdrant_client, get_redis
from search_service.embedding.bge import BGEM3Embedder

log = structlog.get_logger(__name__)
router = APIRouter(tags=["ops"])

_request_count: int = 0
_total_latency_ms: float = 0.0
_cache_hits: int = 0
_cache_misses: int = 0


def record_request(latency_ms: float) -> None:
    global _request_count, _total_latency_ms
    _request_count += 1
    _total_latency_ms += latency_ms


def record_cache(hit: bool) -> None:
    global _cache_hits, _cache_misses
    if hit:
        _cache_hits += 1
    else:
        _cache_misses += 1


@router.get("/health")
async def health(
    qdrant: Annotated[AsyncQdrantClient, Depends(get_qdrant_client)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],  # type: ignore[type-arg]
    embedder: Annotated[BGEM3Embedder, Depends(get_embedder)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> dict:  # type: ignore[type-arg]
    checks: dict[str, str] = {}

    try:
        await qdrant.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        checks["qdrant"] = f"error: {exc}"

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    try:
        session_maker = get_session_maker(settings.mysql_dsn)
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["mysql"] = "ok"
    except Exception as exc:
        checks["mysql"] = f"error: {exc}"

    checks["models"] = "ok" if embedder is not None else "not_loaded"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if all_ok else "degraded", "checks": checks}


@router.get("/metrics")
async def metrics() -> dict:  # type: ignore[type-arg]
    avg_latency = _total_latency_ms / _request_count if _request_count else 0.0
    total_cache = _cache_hits + _cache_misses
    cache_hit_rate = _cache_hits / total_cache if total_cache else 0.0
    return {
        "requests_total": _request_count,
        "avg_latency_ms": round(avg_latency, 2),
        "cache_hits": _cache_hits,
        "cache_misses": _cache_misses,
        "cache_hit_rate": round(cache_hit_rate, 4),
    }
