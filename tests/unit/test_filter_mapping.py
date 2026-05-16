from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from search_service.config import Settings
from search_service.dto.search import FilterSpec
from search_service.vector_store.qdrant import QdrantStore


def _make_store() -> QdrantStore:
    settings = MagicMock(spec=Settings)
    settings.qdrant_collection = "test"
    settings.qdrant_vector_size = 1024
    client = AsyncMock()
    return QdrantStore(client=client, settings=settings)


def test_no_filter_returns_empty_must() -> None:
    store = _make_store()
    f = store._build_filter(FilterSpec())
    assert f.must is None


def test_category_filter() -> None:
    store = _make_store()
    f = store._build_filter(FilterSpec(category="Electronics"))
    assert f.must is not None
    keys = [c.key for c in f.must]
    assert "category" in keys


def test_source_keys_filter() -> None:
    store = _make_store()
    f = store._build_filter(FilterSpec(source_keys=["shop1", "shop2"]))
    assert f.must is not None
    keys = [c.key for c in f.must]
    assert "source_key" in keys


def test_price_range_filter() -> None:
    store = _make_store()
    f = store._build_filter(FilterSpec(price_min=10.0, price_max=100.0))
    assert f.must is not None
    keys = [c.key for c in f.must]
    assert "price" in keys


def test_combined_filter() -> None:
    store = _make_store()
    f = store._build_filter(
        FilterSpec(category="Tools", price_min=5.0, source_keys=["shop1"])
    )
    assert f.must is not None
    assert len(f.must) == 3
