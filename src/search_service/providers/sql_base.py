from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from search_service.db.session import get_session_maker
from search_service.dto.product import ProductDTO


class SQLProviderBase(ABC):
    def __init__(self, mysql_dsn: str) -> None:
        self._session_maker = get_session_maker(mysql_dsn)

    @abstractmethod
    def source_key(self) -> str: ...

    @abstractmethod
    def _pk_column(self) -> str:
        """Name of the primary-key column used for keyset pagination."""
        ...

    @abstractmethod
    def _table_name(self) -> str: ...

    @abstractmethod
    def map_row_to_dto(self, row: Any) -> ProductDTO: ...

    @abstractmethod
    async def find_one(self, source_id: str) -> ProductDTO | None: ...

    async def count(self) -> int:
        async with self._session_maker() as session:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {self._table_name()}"))
            row = result.scalar_one()
            return int(row)

    async def chunked(self, chunk_size: int) -> AsyncIterator[list[ProductDTO]]:
        pk = self._pk_column()
        last_id: Any = 0
        async with self._session_maker() as session:
            while True:
                rows = await self._fetch_chunk(session, pk, last_id, chunk_size)
                if not rows:
                    break
                dtos = [self.map_row_to_dto(r) for r in rows]
                yield dtos
                last_id = getattr(rows[-1], pk)

    async def _fetch_chunk(
        self, session: AsyncSession, pk: str, last_id: Any, chunk_size: int
    ) -> list[Any]:
        stmt = (
            text(
                f"SELECT * FROM {self._table_name()} WHERE {pk} > :last_id ORDER BY {pk} LIMIT :chunk_size"
            )
            .bindparams(last_id=last_id, chunk_size=chunk_size)
        )
        result = await session.execute(stmt)
        return result.fetchall()
