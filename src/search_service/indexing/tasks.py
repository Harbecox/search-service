from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog
from arq import ArqRedis
from arq.connections import RedisSettings

from search_service.config import get_settings
from search_service.embedding.bge import BGEM3Embedder
from search_service.indexing.service import IndexingService
from search_service.providers.registry import ProviderRegistry
from search_service.vector_store.qdrant import QdrantStore

log = structlog.get_logger(__name__)

PROGRESS_KEY_PREFIX = "arq:progress:"


async def _build_indexing_service(ctx: dict) -> IndexingService:  # type: ignore[type-arg]
    return IndexingService(
        embedder=ctx["embedder"],
        vector_store=ctx["vector_store"],
        registry=ctx["registry"],
        chunk_size=ctx["settings"].indexing_chunk_size,
    )


async def reindex_all_task(ctx: dict, recreate: bool = False, job_id: str = "") -> None:  # type: ignore[type-arg]
    svc = await _build_indexing_service(ctx)
    redis: aioredis.Redis = ctx["redis"]  # type: ignore[type-arg]
    if job_id:
        await redis.set(PROGRESS_KEY_PREFIX + job_id, json.dumps({"status": "running", "processed": 0, "total": -1}))
    try:
        await svc.reindex_all(recreate=recreate)
        if job_id:
            await redis.set(PROGRESS_KEY_PREFIX + job_id, json.dumps({"status": "done", "processed": -1, "total": -1}))
    except Exception as exc:
        log.error("reindex_all_failed", error=str(exc))
        if job_id:
            await redis.set(PROGRESS_KEY_PREFIX + job_id, json.dumps({"status": "error", "error": str(exc)}))
        raise


async def reindex_source_task(ctx: dict, source_key: str, recreate: bool = False, job_id: str = "") -> None:  # type: ignore[type-arg]
    svc = await _build_indexing_service(ctx)
    redis: aioredis.Redis = ctx["redis"]  # type: ignore[type-arg]
    if job_id:
        await redis.set(PROGRESS_KEY_PREFIX + job_id, json.dumps({"status": "running", "processed": 0, "total": -1}))
    try:
        await svc.reindex_source(source_key, recreate=recreate)
        if job_id:
            await redis.set(PROGRESS_KEY_PREFIX + job_id, json.dumps({"status": "done"}))
    except Exception as exc:
        log.error("reindex_source_failed", source_key=source_key, error=str(exc))
        if job_id:
            await redis.set(PROGRESS_KEY_PREFIX + job_id, json.dumps({"status": "error", "error": str(exc)}))
        raise


async def index_chunk_task(ctx: dict, source_key: str, source_ids: list[str]) -> None:  # type: ignore[type-arg]
    svc = await _build_indexing_service(ctx)
    for source_id in source_ids:
        await svc.index_one(source_key, source_id)


async def startup(ctx: dict) -> None:  # type: ignore[type-arg]
    settings = get_settings()
    from qdrant_client import AsyncQdrantClient

    ctx["settings"] = settings
    ctx["embedder"] = BGEM3Embedder(
        model_name=settings.embedding_model_name,
        device=settings.embedding_device,
        use_fp16=settings.embedding_use_fp16,
    )
    ctx["qdrant_client"] = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    ctx["vector_store"] = QdrantStore(client=ctx["qdrant_client"], settings=settings)
    ctx["registry"] = ProviderRegistry()
    ctx["registry"].load_from_settings(settings)
    ctx["redis"] = await aioredis.from_url(settings.redis_url)


async def shutdown(ctx: dict) -> None:  # type: ignore[type-arg]
    await ctx["qdrant_client"].close()
    await ctx["redis"].aclose()


def _make_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    redis_settings = _make_redis_settings()
    functions = [reindex_all_task, reindex_source_task, index_chunk_task]
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = 86400  # 24h — full reindex on CPU can take hours
