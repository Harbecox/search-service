from __future__ import annotations

from typing import Any

from sqlalchemy import text

from search_service.dto.product import ProductDTO
from search_service.providers.sql_base import SQLProviderBase


class SlamisProvider(SQLProviderBase):
    def source_key(self) -> str:
        return "slamis"

    def _pk_column(self) -> str:
        return "id"

    def _table_name(self) -> str:
        return "slamis"

    def map_row_to_dto(self, row: Any) -> ProductDTO:
        attrs: dict[str, str] = {}

        if row.brand_code:
            attrs["Бренд"] = str(row.brand_code)
        if row.unit_name:
            attrs["Единица"] = str(row.unit_name)
        if row.dimensions:
            attrs["Размеры"] = str(row.dimensions)
        if row.weight:
            attrs["Вес"] = f"{row.weight} кг"
        if row.pack_quantity and int(row.pack_quantity) > 1:
            attrs["Упаковка"] = str(row.pack_quantity)

        # Добавить specification_text как отдельный атрибут для поиска
        if row.specification_text:
            attrs["Характеристики"] = str(row.specification_text)[:500]

        return ProductDTO(
            source_key=self.source_key(),
            source_id=str(row.id),
            name=str(row.name),
            description=row.preview_text or None,
            price=float(row.price_retail) if row.price_retail else None,
            category=row.category_code or None,
            image_url=row.image_thumb or row.image_full or None,
            attributes=attrs,
            meta={
                "sku": row.sku,
                "code": row.code,
                "brand_code": row.brand_code,
                "price_wholesale": str(row.price_wholesale),
                "price_final": str(row.price_final),
                "flag_new": bool(row.flag_new),
                "flag_onsale": bool(row.flag_onsale),
                "stock_free": int(row.stock_free),
            },
        )

    async def count(self) -> int:
        async with self._session_maker() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM slamis WHERE active = 1")
            )
            return int(result.scalar_one())

    async def find_one(self, source_id: str) -> ProductDTO | None:
        async with self._session_maker() as session:
            result = await session.execute(
                text("SELECT * FROM slamis WHERE id = :id AND active = 1")
                .bindparams(id=int(source_id))
            )
            row = result.fetchone()
            return self.map_row_to_dto(row) if row else None

    async def _fetch_chunk(self, session: Any, pk: str, last_id: Any, chunk_size: int) -> list[Any]:
        stmt = text(
            "SELECT * FROM slamis WHERE id > :last_id AND active = 1 "
            "ORDER BY id LIMIT :chunk_size"
        ).bindparams(last_id=last_id, chunk_size=chunk_size)
        result = await session.execute(stmt)
        return result.fetchall()
