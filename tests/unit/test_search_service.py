from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from search_service.cache.redis_cache import RedisCache
from search_service.config import Settings
from search_service.dto.search import FilterSpec, SearchRequest
from search_service.search.service import SearchService
from search_service.vector_store.base import SearchCandidate


def _make_settings(top_k_vector: int = 50, top_k_final: int = 3, rerank_threshold: int = 2) -> Settings:
    s = MagicMock(spec=Settings)
    s.search_top_k_vector = top_k_vector
    s.search_top_k_final = top_k_final
    s.search_rerank_threshold = rerank_threshold
    return s


def _make_candidates(n: int) -> list[SearchCandidate]:
    return [
        SearchCandidate(
            global_id=f"shop:{i}",
            score=1.0 - i * 0.01,
            payload={"text": f"product text {i}", "source_key": "shop", "source_id": str(i)},
        )
        for i in range(n)
    ]


@pytest.fixture
def embedder() -> AsyncMock:
    m = AsyncMock()
    m.embed.return_value = [0.1] * 1024
    return m


@pytest.fixture
def reranker() -> AsyncMock:
    m = AsyncMock()
    m.rerank.return_value = [("shop:0", 0.9), ("shop:1", 0.7), ("shop:2", 0.5)]
    return m


@pytest.fixture
def cache() -> AsyncMock:
    m = AsyncMock(spec=RedisCache)
    m.get_or_set_embedding.side_effect = lambda q, factory: factory()
    return m


@pytest.fixture
def registry() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_search_without_reranker(embedder: AsyncMock, reranker: AsyncMock, cache: AsyncMock, registry: MagicMock) -> None:
    store = AsyncMock()
    store.search.return_value = _make_candidates(2)
    settings = _make_settings(rerank_threshold=10)

    svc = SearchService(embedder, store, reranker, cache, registry, settings)
    resp = await svc.search(SearchRequest(query="bolt", use_reranker=False, limit=3))

    assert len(resp.hits) == 2
    assert resp.reranked is False
    reranker.rerank.assert_not_called()


@pytest.mark.asyncio
async def test_search_with_reranker_above_threshold(embedder: AsyncMock, reranker: AsyncMock, cache: AsyncMock, registry: MagicMock) -> None:
    store = AsyncMock()
    store.search.return_value = _make_candidates(5)
    settings = _make_settings(rerank_threshold=2)

    svc = SearchService(embedder, store, reranker, cache, registry, settings)
    resp = await svc.search(SearchRequest(query="bolt", use_reranker=True, limit=3))

    assert resp.reranked is True
    reranker.rerank.assert_called_once()


@pytest.mark.asyncio
async def test_search_hydrates_from_db(embedder: AsyncMock, reranker: AsyncMock, cache: AsyncMock, registry: MagicMock) -> None:
    from search_service.dto.product import ProductDTO

    store = AsyncMock()
    store.search.return_value = _make_candidates(1)
    settings = _make_settings(rerank_threshold=10)

    provider = AsyncMock()
    provider.find_one.return_value = ProductDTO(source_key="shop", source_id="0", name="Bolt")
    registry.get.return_value = provider

    svc = SearchService(embedder, store, reranker, cache, registry, settings)
    resp = await svc.search(SearchRequest(query="bolt", hydrate_from_db=True, limit=3))

    assert resp.hits[0].product is not None
    assert resp.hits[0].product.name == "Bolt"
