from __future__ import annotations

import pytest
from qdrant_client import AsyncQdrantClient

from search_service.config import Settings
from search_service.dto.search import FilterSpec
from search_service.vector_store.base import VectorPoint
from search_service.vector_store.qdrant import QdrantStore

# Requires Qdrant running on localhost:6333 (docker compose up -d qdrant)
pytestmark = pytest.mark.integration


@pytest.fixture
async def store() -> QdrantStore:
    settings = Settings(  # type: ignore[call-arg]
        api_bearer_token="test",
        mysql_dsn="mysql+aiomysql://user:pass@localhost/db",
        qdrant_collection="test_integration",
    )
    client = AsyncQdrantClient(host="localhost", port=6333)
    s = QdrantStore(client=client, settings=settings)
    await s.recreate_collection()
    return s


@pytest.mark.asyncio
async def test_upsert_and_search(store: QdrantStore) -> None:
    points = [
        VectorPoint(
            global_id="shop:1",
            vector=[0.1] * 1024,
            payload={"source_key": "shop", "price": 10.0, "text": "test product"},
        )
    ]
    await store.upsert(points)
    results = await store.search(vector=[0.1] * 1024, filters=None, limit=5)
    assert any(r.global_id == "shop:1" for r in results)


@pytest.mark.asyncio
async def test_delete(store: QdrantStore) -> None:
    points = [VectorPoint(global_id="shop:99", vector=[0.5] * 1024, payload={"source_key": "shop"})]
    await store.upsert(points)
    await store.delete(["shop:99"])
    results = await store.search(vector=[0.5] * 1024, filters=None, limit=10)
    assert not any(r.global_id == "shop:99" for r in results)


@pytest.mark.asyncio
async def test_filter_by_source_key(store: QdrantStore) -> None:
    points = [
        VectorPoint(global_id="a:1", vector=[0.1] * 1024, payload={"source_key": "a"}),
        VectorPoint(global_id="b:1", vector=[0.1] * 1024, payload={"source_key": "b"}),
    ]
    await store.upsert(points)
    results = await store.search(
        vector=[0.1] * 1024,
        filters=FilterSpec(source_keys=["a"]),
        limit=10,
    )
    assert all(r.global_id.startswith("a:") for r in results)
