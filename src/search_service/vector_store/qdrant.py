from __future__ import annotations

import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from search_service.config import Settings
from search_service.dto.search import FilterSpec
from search_service.vector_store.base import SearchCandidate, VectorPoint


class QdrantStore:
    def __init__(self, client: AsyncQdrantClient, settings: Settings) -> None:
        self._client = client
        self._collection = settings.qdrant_collection
        self._vector_size = settings.qdrant_vector_size

    async def ensure_collection(self) -> None:
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if self._collection not in existing:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(
                    size=self._vector_size,
                    distance=qm.Distance.COSINE,
                ),
            )
            await self._client.create_payload_index(self._collection, "source_key", qm.PayloadSchemaType.KEYWORD)
            await self._client.create_payload_index(self._collection, "category", qm.PayloadSchemaType.KEYWORD)
            await self._client.create_payload_index(self._collection, "price", qm.PayloadSchemaType.FLOAT)
            await self._client.create_payload_index(self._collection, "global_id", qm.PayloadSchemaType.KEYWORD)

    async def recreate_collection(self) -> None:
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if self._collection in existing:
            await self._client.delete_collection(self._collection)
        await self.ensure_collection()

    async def upsert(self, points: list[VectorPoint]) -> None:
        qdrant_points = [
            qm.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, p.global_id)),
                vector=p.vector,
                payload={"global_id": p.global_id, **p.payload},
            )
            for p in points
        ]
        await self._client.upsert(collection_name=self._collection, points=qdrant_points)

    async def search(
        self,
        vector: list[float],
        filters: FilterSpec | None,
        limit: int,
    ) -> list[SearchCandidate]:
        qdrant_filter = self._build_filter(filters) if filters else None
        response = await self._client.query_points(
            collection_name=self._collection,
            query=vector,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )
        return [
            SearchCandidate(global_id=r.payload["global_id"], score=r.score, payload=r.payload)
            for r in response.points
            if r.payload
        ]

    async def delete(self, global_ids: list[str]) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[qm.FieldCondition(key="global_id", match=qm.MatchAny(any=global_ids))]
                )
            ),
        )

    async def count(self) -> int:
        result = await self._client.count(collection_name=self._collection, exact=True)
        return result.count

    def _build_filter(self, filters: FilterSpec) -> qm.Filter:
        must: list[qm.Condition] = []

        if filters.category:
            must.append(qm.FieldCondition(key="category", match=qm.MatchValue(value=filters.category)))

        if filters.source_keys:
            must.append(
                qm.FieldCondition(key="source_key", match=qm.MatchAny(any=filters.source_keys))
            )

        price_range: dict[str, float] = {}
        if filters.price_min is not None:
            price_range["gte"] = filters.price_min
        else:
            # Если задан любой ценовой фильтр — исключаем товары без цены (price=0)
            if filters.price_max is not None:
                price_range["gt"] = 0.0
        if filters.price_max is not None:
            price_range["lte"] = filters.price_max
        if price_range:
            must.append(qm.FieldCondition(key="price", range=qm.Range(**price_range)))

        return qm.Filter(must=must if must else None)
