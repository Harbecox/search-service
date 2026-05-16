from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from search_service.dto.product import ProductDTO
from search_service.providers.sql_base import SQLProviderBase


class ProductsProvider(SQLProviderBase):
    def source_key(self) -> str:
        return "products"

    def _pk_column(self) -> str:
        return "id"

    def _table_name(self) -> str:
        return "products"

    def map_row_to_dto(self, row: Any) -> ProductDTO:
        raw = row.attributes
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = []

        # [{"name": "...", "value": "..."}, ...]  →  {"name": "value"}
        if isinstance(raw, list):
            attrs = {
                str(item["name"]): str(item["value"])
                for item in raw
                if isinstance(item, dict) and "name" in item and "value" in item
            }
        elif isinstance(raw, dict):
            attrs = {str(k): str(v) for k, v in raw.items()}
        else:
            attrs = {}

        return ProductDTO(
            source_key=self.source_key(),
            source_id=str(row.id),
            name=str(row.title),
            description=row.description or None,
            price=float(row.price) if row.price is not None else None,
            attributes=attrs,
            meta={"sku": row.sku} if row.sku else {},
        )

    async def find_one(self, source_id: str) -> ProductDTO | None:
        async with self._session_maker() as session:
            result = await session.execute(
                text("SELECT * FROM products WHERE id = :id").bindparams(id=int(source_id))
            )
            row = result.fetchone()
            return self.map_row_to_dto(row) if row else None
