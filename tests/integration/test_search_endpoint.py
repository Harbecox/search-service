from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    with (
        patch("search_service.deps._embedder", new=AsyncMock()),
        patch("search_service.deps._reranker", new=AsyncMock()),
        patch("search_service.deps._qdrant", new=AsyncMock()),
        patch("search_service.deps._redis", new=AsyncMock()),
        patch("search_service.deps._registry", new=MagicMock()),
    ):
        from search_service.main import app

        return TestClient(app, raise_server_exceptions=True)


def test_search_requires_auth(client: TestClient) -> None:
    resp = client.post("/search", json={"query": "bolt"})
    assert resp.status_code == 403


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert "checks" in body
