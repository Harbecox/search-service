from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from search_service.auth import require_auth
from search_service.cache.redis_cache import RedisCache
from search_service.config import Settings, get_settings
from search_service.deps import (
    get_embedder,
    get_qdrant_store,
    get_redis_cache,
    get_registry,
    get_reranker,
)
from search_service.dto.search import SearchRequest, SearchResponse
from search_service.embedding.bge import BGEM3Embedder
from search_service.providers.registry import ProviderRegistry
from search_service.reranker.bge import BGERerankerV2
from search_service.search.service import SearchService
from search_service.vector_store.qdrant import QdrantStore

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse, dependencies=[Depends(require_auth)])
async def search(
    req: SearchRequest,
    embedder: Annotated[BGEM3Embedder, Depends(get_embedder)],
    vector_store: Annotated[QdrantStore, Depends(get_qdrant_store)],
    reranker: Annotated[BGERerankerV2, Depends(get_reranker)],
    cache: Annotated[RedisCache, Depends(get_redis_cache)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    svc = SearchService(
        embedder=embedder,
        vector_store=vector_store,
        reranker=reranker,
        cache=cache,
        registry=registry,
        settings=settings,
    )
    return await svc.search(req)
