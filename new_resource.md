# Как добавить новую таблицу MySQL как источник поиска

Допустим, у вас есть таблица `spare_parts` со своей структурой и вы хотите искать по ней наравне с `products`.

---

## Шаг 1 — Изучить структуру таблицы

```sql
DESCRIBE spare_parts;
-- или
SELECT * FROM spare_parts LIMIT 3;
```

Запишите:
- Имя таблицы
- Название колонки с PRIMARY KEY (для keyset-пагинации)
- Какие колонки соответствуют: название, описание, цена, категория, изображение

---

## Шаг 2 — Создать файл провайдера

Скопируйте `src/search_service/providers/products.py` в новый файл:

```bash
cp src/search_service/providers/products.py src/search_service/providers/spare_parts.py
```

Откройте и отредактируйте `spare_parts.py`:

```python
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from search_service.dto.product import ProductDTO
from search_service.providers.sql_base import SQLProviderBase


class SparePartsProvider(SQLProviderBase):

    def source_key(self) -> str:
        # Уникальный ключ — используется как префикс global_id: "spare_parts:123"
        return "spare_parts"

    def _pk_column(self) -> str:
        # Колонка PRIMARY KEY вашей таблицы (для пагинации)
        return "id"

    def _table_name(self) -> str:
        return "spare_parts"

    def map_row_to_dto(self, row: Any) -> ProductDTO:
        # Маппинг колонок таблицы → ProductDTO
        # Подстройте под реальные названия колонок вашей таблицы

        return ProductDTO(
            source_key=self.source_key(),
            source_id=str(row.id),           # всегда str
            name=str(row.name),              # название — обязательно
            description=getattr(row, "description", None),
            price=float(row.price) if getattr(row, "price", None) is not None else None,
            category=getattr(row, "category", None),
            image_url=getattr(row, "image_url", None),
            # attributes — если есть JSON-колонка вида [{"name":"..","value":".."}]:
            attributes=self._parse_attributes(getattr(row, "attributes", None)),
            # meta — любые дополнительные поля
            meta={"sku": row.sku} if getattr(row, "sku", None) else {},
        )

    def _parse_attributes(self, raw: Any) -> dict[str, str]:
        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        if isinstance(raw, list):
            return {
                str(item["name"]): str(item["value"])
                for item in raw
                if isinstance(item, dict) and "name" in item and "value" in item
            }
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        return {}

    async def find_one(self, source_id: str) -> ProductDTO | None:
        async with self._session_maker() as session:
            result = await session.execute(
                text("SELECT * FROM spare_parts WHERE id = :id")
                .bindparams(id=int(source_id))
            )
            row = result.fetchone()
            return self.map_row_to_dto(row) if row else None
```

---

## Шаг 3 — Зарегистрировать провайдер в .env

Откройте `.env` и добавьте новый класс через запятую:

```dotenv
# Один провайдер:
PROVIDERS_CLASSES=search_service.providers.products.ProductsProvider

# Два провайдера:
PROVIDERS_CLASSES=search_service.providers.products.ProductsProvider,search_service.providers.spare_parts.SparePartsProvider
```

---

## Шаг 4 — Проверить провайдер

```bash
python -c "
import asyncio, sys
sys.path.insert(0, 'src')

async def main():
    from search_service.config import get_settings
    from search_service.providers.spare_parts import SparePartsProvider

    s = get_settings()
    p = SparePartsProvider(mysql_dsn=s.mysql_dsn)

    count = await p.count()
    print('Всего строк:', count)

    async for chunk in p.chunked(3):
        for item in chunk:
            print(item.global_id, '|', item.name[:50])
            print('  price:', item.price, 'attrs:', list(item.attributes.items())[:2])
        break

asyncio.run(main())
"
```

Убедитесь что данные читаются правильно и `name` не пустой.

---

## Шаг 5 — Проиндексировать новый источник

```bash
# Перезапустить воркер (чтобы подхватил новый провайдер):
# Ctrl+C в терминале воркера, затем:
python -m search_service.cli worker

# Запустить индексацию только нового источника:
python -m search_service.cli reindex --source spare_parts

# Следить за прогрессом:
curl http://localhost:6333/collections/products | python -c "import sys,json; print('points:', json.load(sys.stdin)['result']['points_count'])"
```

---

## Шаг 6 — Перезапустить API и проверить поиск

```bash
# Перезапустить uvicorn (Ctrl+C → снова запустить)
uvicorn search_service.main:app --host 0.0.0.0 --port 8000

# Список источников:
curl -s http://localhost:8000/sources \
  -H "Authorization: Bearer ВАШ_ТОКЕН" | python -m json.tool

# Поиск только по новому источнику:
curl -s -X POST http://localhost:8000/search \
  -H "Authorization: Bearer ВАШ_ТОКЕН" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "ваш поисковый запрос",
    "filters": {"source_keys": ["spare_parts"]},
    "limit": 5
  }' | python -m json.tool

# Поиск по всем источникам сразу:
curl -s -X POST http://localhost:8000/search \
  -H "Authorization: Bearer ВАШ_ТОКЕН" \
  -H "Content-Type: application/json" \
  -d '{"query": "ваш поисковый запрос", "limit": 10}' | python -m json.tool
```

---

## Нестандартные случаи

### PRIMARY KEY не `id`

Если в таблице нет `id`, например PK называется `article_id`:

```python
def _pk_column(self) -> str:
    return "article_id"
```

И в `find_one` соответственно:
```python
.bindparams(id=source_id)  # не int() если PK строковый
```

### Составной PRIMARY KEY или нет нормального PK

Добавьте в таблицу `AUTO_INCREMENT` колонку или используйте `ROWNUM`:

```python
async def _fetch_chunk(self, session, pk, last_id, chunk_size):
    stmt = text("""
        SELECT * FROM my_table
        ORDER BY id
        LIMIT :chunk_size OFFSET :offset
    """).bindparams(chunk_size=chunk_size, offset=last_id)
    result = await session.execute(stmt)
    return result.fetchall()
```

В этом случае переопределите `chunked()` целиком в вашем классе.

### Фильтрация по active/published

Если нужно индексировать только активные товары:

```python
async def _fetch_chunk(self, session, pk, last_id, chunk_size):
    stmt = text("""
        SELECT * FROM spare_parts
        WHERE id > :last_id AND is_active = 1
        ORDER BY id
        LIMIT :chunk_size
    """).bindparams(last_id=last_id, chunk_size=chunk_size)
    result = await session.execute(stmt)
    return result.fetchall()

async def count(self) -> int:
    async with self._session_maker() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM spare_parts WHERE is_active = 1")
        )
        return int(result.scalar_one())
```

### Название из нескольких колонок

```python
name=f"{row.brand} {row.model} {row.article}".strip(),
```

---

## Точечное обновление из Laravel

Когда товар изменился — не нужно переиндексировать всё. Вызовите из Laravel:

```bash
# Обновить один товар:
curl -X POST http://localhost:8000/index/product \
  -H "Authorization: Bearer ВАШ_ТОКЕН" \
  -H "Content-Type: application/json" \
  -d '{"source_key": "spare_parts", "source_id": "456"}'

# Удалить товар из индекса:
curl -X DELETE http://localhost:8000/index/product/spare_parts:456 \
  -H "Authorization: Bearer ВАШ_ТОКЕН"
```
