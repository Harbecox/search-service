from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from search_service.dto.search import FilterSpec


class VectorPoint(BaseModel):
    global_id: str
    vector: list[float]
    payload: dict  # type: ignore[type-arg]


class SearchCandidate(BaseModel):
    global_id: str
    score: float
    payload: dict  # type: ignore[type-arg]


@runtime_checkable
class VectorStore(Protocol):
    async def ensure_collection(self) -> None: ...
    async def upsert(self, points: list[VectorPoint]) -> None: ...
    async def search(
        self,
        vector: list[float],
        filters: FilterSpec | None,
        limit: int,
    ) -> list[SearchCandidate]: ...
    async def delete(self, global_ids: list[str]) -> None: ...
    async def count(self) -> int: ...
