from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, FastAPI
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from search_service.cache.redis_cache import RedisCache
from search_service.config import Settings, get_settings
from search_service.db.session import get_session_maker
from search_service.embedding.bge import BGEM3Embedder
from search_service.providers.registry import ProviderRegistry
from search_service.reranker.bge import BGERerankerV2
from search_service.vector_store.qdrant import QdrantStore

log = structlog.get_logger(__name__)

# --- Module-level singletons populated during lifespan ---

_embedder: BGEM3Embedder | None = None
_reranker: BGERerankerV2 | None = None
_qdrant: AsyncQdrantClient | None = None
_redis: aioredis.Redis | None = None  # type: ignore[type-arg]
_registry: ProviderRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _embedder, _reranker, _qdrant, _redis, _registry

    settings = get_settings()

    log.info("loading_embedding_model", model=settings.embedding_model_name, device=settings.embedding_device)
    _embedder = BGEM3Embedder(
        model_name=settings.embedding_model_name,
        device=settings.embedding_device,
        use_fp16=settings.embedding_use_fp16,
    )

    log.info("loading_reranker_model", model=settings.reranker_model_name, device=settings.reranker_device)
    _reranker = BGERerankerV2(
        model_name=settings.reranker_model_name,
        device=settings.reranker_device,
    )

    _qdrant = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    _redis = await aioredis.from_url(settings.redis_url, decode_responses=False)

    _registry = ProviderRegistry()
    _registry.load_from_settings(settings)

    log.info("startup_complete")
    yield

    log.info("shutting_down")
    await _qdrant.close()
    await _redis.aclose()


# --- FastAPI dependency providers ---

def get_embedder() -> BGEM3Embedder:
    assert _embedder is not None, "Embedder not initialised"
    return _embedder


def get_reranker() -> BGERerankerV2:
    assert _reranker is not None, "Reranker not initialised"
    return _reranker


def get_qdrant_client() -> AsyncQdrantClient:
    assert _qdrant is not None, "Qdrant client not initialised"
    return _qdrant


def get_qdrant_store(
    client: Annotated[AsyncQdrantClient, Depends(get_qdrant_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> QdrantStore:
    return QdrantStore(client=client, settings=settings)


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    assert _redis is not None, "Redis not initialised"
    return _redis


def get_redis_cache(
    redis: Annotated[aioredis.Redis, Depends(get_redis)],  # type: ignore[type-arg]
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedisCache:
    return RedisCache(redis=redis, ttl=settings.cache_query_embedding_ttl)


def get_registry() -> ProviderRegistry:
    assert _registry is not None, "Registry not initialised"
    return _registry


async def get_db_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AsyncSession]:
    session_maker = get_session_maker(settings.mysql_dsn)
    async with session_maker() as session:
        yield session
