from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from search_service.auth import require_auth
from search_service.deps import get_qdrant_store, get_registry
from search_service.providers.registry import ProviderRegistry
from search_service.vector_store.qdrant import QdrantStore

router = APIRouter(prefix="/sources", tags=["sources"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_sources(
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    vector_store: Annotated[QdrantStore, Depends(get_qdrant_store)],
) -> list[dict]:  # type: ignore[type-arg]
    result = []
    for provider in registry.all():
        sk = provider.source_key()
        count_db = await provider.count()
        result.append({"source_key": sk, "count_in_db": count_db})
    return result
