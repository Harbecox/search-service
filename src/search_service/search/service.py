from __future__ import annotations

import time

import structlog

from search_service.cache.redis_cache import RedisCache
from search_service.config import Settings
from search_service.dto.product import ProductDTO
from search_service.dto.search import SearchHit, SearchRequest, SearchResponse
from search_service.embedding.bge import BGEM3Embedder
from search_service.providers.registry import ProviderRegistry
from search_service.reranker.bge import BGERerankerV2
from search_service.vector_store.qdrant import QdrantStore

log = structlog.get_logger(__name__)


class SearchService:
    def __init__(
        self,
        embedder: BGEM3Embedder,
        vector_store: QdrantStore,
        reranker: BGERerankerV2,
        cache: RedisCache,
        registry: ProviderRegistry,
        settings: Settings,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._reranker = reranker
        self._cache = cache
        self._registry = registry
        self._settings = settings

    async def search(self, req: SearchRequest) -> SearchResponse:
        t0 = time.monotonic()

        vector = await self._cache.get_or_set_embedding(
            req.query,
            lambda: self._embedder.embed(req.query),
        )

        candidates = await self._vector_store.search(
            vector=vector,
            filters=req.filters,
            limit=self._settings.search_top_k_vector,
        )

        reranked = False
        if candidates and len(candidates) > self._settings.search_rerank_threshold and req.use_reranker:
            pairs = [(c.global_id, c.payload.get("text", "")) for c in candidates]
            ranked = await self._reranker.rerank(req.query, pairs, top_k=req.limit)
            score_map = dict(ranked)
            hits = [
                SearchHit(global_id=gid, score=score)
                for gid, score in ranked
            ]
            reranked = True
        else:
            hits = [
                SearchHit(global_id=c.global_id, score=c.score)
                for c in candidates[: req.limit]
            ]

        if req.hydrate_from_db:
            hits = await self._hydrate(hits)

        took_ms = (time.monotonic() - t0) * 1000
        log.info("search_done", query=req.query, hits=len(hits), took_ms=round(took_ms, 2), reranked=reranked)

        return SearchResponse(query=req.query, hits=hits, took_ms=took_ms, reranked=reranked)

    async def _hydrate(self, hits: list[SearchHit]) -> list[SearchHit]:
        result: list[SearchHit] = []
        for hit in hits:
            source_key, source_id = hit.global_id.split(":", 1)
            try:
                provider = self._registry.get(source_key)
                product = await provider.find_one(source_id)
            except KeyError:
                product = None
            result.append(hit.model_copy(update={"product": product}))
        return result
