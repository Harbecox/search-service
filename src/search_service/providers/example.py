from __future__ import annotations

from typing import Any

from search_service.dto.product import ProductDTO
from search_service.providers.sql_base import SQLProviderBase


class ExampleProvider(SQLProviderBase):
    """
    TODO: Replace with your real table structure.

    Steps to add a new provider:
    1. Copy this file and rename the class.
    2. Override source_key(), _pk_column(), _table_name(), map_row_to_dto(), find_one().
    3. Add the dotted path "search_service.providers.mymodule.MyProvider"
       to PROVIDERS_CLASSES in .env.
    """

    def source_key(self) -> str:
        return "example"

    def _pk_column(self) -> str:
        return "id"

    def _table_name(self) -> str:
        return "products"  # TODO: change to your table name

    def map_row_to_dto(self, row: Any) -> ProductDTO:
        # TODO: map row columns to ProductDTO fields
        return ProductDTO(
            source_key=self.source_key(),
            source_id=str(row.id),
            name=row.title,
            description=getattr(row, "description", None),
            price=getattr(row, "price", None),
            category=getattr(row, "category", None),
            image_url=getattr(row, "image_url", None),
        )

    async def find_one(self, source_id: str) -> ProductDTO | None:
        from sqlalchemy import text

        async with self._session_maker() as session:
            result = await session.execute(
                text(f"SELECT * FROM {self._table_name()} WHERE id = :id").bindparams(id=int(source_id))
            )
            row = result.fetchone()
            return self.map_row_to_dto(row) if row else None
