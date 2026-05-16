from __future__ import annotations

import structlog

from search_service.dto.product import ProductDTO
from search_service.embedding.bge import BGEM3Embedder
from search_service.providers.registry import ProviderRegistry
from search_service.vector_store.base import VectorPoint
from search_service.vector_store.qdrant import QdrantStore

log = structlog.get_logger(__name__)


class IndexingService:
    def __init__(
        self,
        embedder: BGEM3Embedder,
        vector_store: QdrantStore,
        registry: ProviderRegistry,
        chunk_size: int = 128,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._registry = registry
        self._chunk_size = chunk_size

    async def reindex_all(self, recreate: bool = False) -> None:
        if recreate:
            await self._vector_store.recreate_collection()
        else:
            await self._vector_store.ensure_collection()

        for provider in self._registry.all():
            await self.reindex_source(provider.source_key(), recreate=False)

    async def reindex_source(self, source_key: str, recreate: bool = False) -> None:
        if recreate:
            await self._vector_store.recreate_collection()
        else:
            await self._vector_store.ensure_collection()

        provider = self._registry.get(source_key)
        processed = 0
        async for chunk in provider.chunked(self._chunk_size):
            await self._index_chunk(chunk)
            processed += len(chunk)
            log.info("indexing_progress", source_key=source_key, processed=processed)

    async def index_one(self, source_key: str, source_id: str) -> None:
        provider = self._registry.get(source_key)
        product = await provider.find_one(source_id)
        if product is None:
            log.warning("product_not_found", source_key=source_key, source_id=source_id)
            return
        await self._index_chunk([product])

    async def _index_chunk(self, products: list[ProductDTO]) -> None:
        texts = [p.to_embedding_text() for p in products]
        vectors = await self._embedder.embed_batch(texts)
        points = [
            VectorPoint(
                global_id=p.global_id,
                vector=v,
                payload={
                    "source_key": p.source_key,
                    "source_id": p.source_id,
                    "name": p.name,
                    "category": p.category,
                    "price": p.price,
                    "image_url": p.image_url,
                    "text": t,
                },
            )
            for p, v, t in zip(products, vectors, texts)
        ]
        await self._vector_store.upsert(points)
