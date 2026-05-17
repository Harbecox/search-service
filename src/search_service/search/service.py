from __future__ import annotations

import time

import structlog

from search_service.cache.redis_cache import RedisCache
from search_service.config import Settings
from search_service.dto.product import ProductDTO
from search_service.dto.search import (
    FilterSpec,
    ParsedQuery,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from search_service.embedding.bge import BGEM3Embedder
from search_service.providers.registry import ProviderRegistry
from search_service.reranker.bge import BGERerankerV2
from search_service.search.query_parser import OllamaQueryParser
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
        self._parser = OllamaQueryParser(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout,
        ) if settings.ollama_enabled else None

    async def search(self, req: SearchRequest) -> SearchResponse:
        t0 = time.monotonic()

        # Шаг 1 — парсинг запроса (опционально)
        parsed: ParsedQuery | None = None
        search_query = req.query
        effective_filters = req.filters

        use_parser = req.use_query_parser or (
            self._settings.ollama_enabled and req.use_query_parser
        )

        if use_parser and self._parser is not None:
            parsed = await self._parser.parse(req.query)
            search_query = parsed.query

            # Смёржить фильтры из парсера с фильтрами из запроса
            effective_filters = _merge_filters(req.filters, parsed)

        # Шаг 2 — эмбеддинг (с кешем)
        vector = await self._cache.get_or_set_embedding(
            search_query,
            lambda: self._embedder.embed(search_query),
        )

        # Шаг 3 — векторный поиск
        candidates = await self._vector_store.search(
            vector=vector,
            filters=effective_filters,
            limit=self._settings.search_top_k_vector,
        )

        # Шаг 4 — исключить нежелательные результаты (из parsed.exclude)
        if parsed and parsed.exclude:
            candidates = _apply_exclude(candidates, parsed.exclude)

        # Шаг 5 — reranking (опционально)
        reranked = False
        if candidates and len(candidates) > self._settings.search_rerank_threshold and req.use_reranker:
            pairs = [(c.global_id, c.payload.get("text", "")) for c in candidates]
            ranked = await self._reranker.rerank(search_query, pairs, top_k=req.limit)
            hits = [SearchHit(global_id=gid, score=score) for gid, score in ranked]
            reranked = True
        else:
            hits = [
                SearchHit(global_id=c.global_id, score=c.score)
                for c in candidates[: req.limit]
            ]

        # Шаг 6 — гидрация из БД (опционально)
        if req.hydrate_from_db:
            hits = await self._hydrate(hits)

        took_ms = (time.monotonic() - t0) * 1000
        log.info(
            "search_done",
            query=req.query,
            search_query=search_query,
            hits=len(hits),
            took_ms=round(took_ms, 2),
            reranked=reranked,
            parsed=parsed is not None,
        )

        return SearchResponse(
            query=req.query,
            hits=hits,
            took_ms=took_ms,
            reranked=reranked,
            parsed_query=parsed,
        )

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


def _merge_filters(
    existing: FilterSpec | None,
    parsed: ParsedQuery,
) -> FilterSpec | None:
    if not any([parsed.price_min, parsed.price_max, parsed.category]):
        return existing

    base = existing.model_copy() if existing else FilterSpec()

    if parsed.price_min is not None and base.price_min is None:
        base = base.model_copy(update={"price_min": parsed.price_min})
    if parsed.price_max is not None and base.price_max is None:
        base = base.model_copy(update={"price_max": parsed.price_max})
    if parsed.category and base.category is None:
        base = base.model_copy(update={"category": parsed.category})

    return base


def _apply_exclude(candidates: list, exclude: list[str]) -> list:
    def _is_excluded(candidate) -> bool:
        text = (candidate.payload.get("text") or candidate.payload.get("name") or "").lower()
        return any(term in text for term in exclude)

    filtered = [c for c in candidates if not _is_excluded(c)]
    # Если всё исключено — вернуть оригинал чтобы не было пустого результата
    return filtered if filtered else candidates
