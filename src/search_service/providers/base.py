from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from search_service.dto.product import ProductDTO


@runtime_checkable
class ProductProvider(Protocol):
    def source_key(self) -> str: ...
    async def chunked(self, chunk_size: int) -> AsyncIterator[list[ProductDTO]]: ...
    async def find_one(self, source_id: str) -> ProductDTO | None: ...
    async def count(self) -> int: ...
