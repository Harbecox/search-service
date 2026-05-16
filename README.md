# search-service

Python-микросервис AI-поиска товаров на базе FastAPI + Qdrant + BAAI/bge-m3.

## Архитектура

```
Laravel (HTTP Bearer) → FastAPI
                             ├── SearchService → BGEM3Embedder → RedisCache
                             │                → QdrantStore (векторный поиск)
                             │                → BGERerankerV2 (переранжирование)
                             ├── IndexingService → ARQ (Redis очередь)
                             │                   → ProductProvider → MySQL
                             └── REST API: /search /index /sources /health /metrics
```

## Требования

- Python 3.11+
- Docker (для Qdrant)
- Redis (уже запущен на хосте)
- MySQL (read-only доступ к таблицам товаров)

## Установка

```bash
# 1. Установить зависимости через uv
uv sync

# 2. Скопировать и заполнить конфиг
cp .env.example .env
# Отредактируйте .env: API_BEARER_TOKEN, MYSQL_DSN, REDIS_URL

# 3. Запустить Qdrant
docker compose up -d qdrant
```

## Первый запуск

```bash
# Создать коллекцию в Qdrant
python -m search_service.cli init-collection

# Зарегистрировать провайдер в .env:
# PROVIDERS_CLASSES=search_service.providers.example.ExampleProvider

# Запустить воркер (в отдельном терминале)
python -m search_service.cli worker

# Запустить полную переиндексацию
python -m search_service.cli reindex

# Запустить API
uvicorn search_service.main:app --host 0.0.0.0 --port 8000
```

## Примеры запросов

```bash
TOKEN="your-token-here"

# Поиск
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "болт нержавеющий M6", "limit": 5}'

# Поиск с фильтрами
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "дрель", "filters": {"category": "Инструменты", "price_max": 5000}, "limit": 10}'

# Переиндексировать всё
curl -X POST http://localhost:8000/index/reindex \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"recreate_collection": false}'

# Переиндексировать один источник
curl -X POST http://localhost:8000/index/reindex \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_keys": ["example"]}'

# Статус задачи
curl http://localhost:8000/index/jobs/{job_id} \
  -H "Authorization: Bearer $TOKEN"

# Индексировать один товар (синхронно, из Laravel)
curl -X POST http://localhost:8000/index/product \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_key": "example", "source_id": "123"}'

# Удалить товар из индекса
curl -X DELETE http://localhost:8000/index/product/example:123 \
  -H "Authorization: Bearer $TOKEN"

# Список источников
curl http://localhost:8000/sources \
  -H "Authorization: Bearer $TOKEN"

# Health check
curl http://localhost:8000/health

# Метрики
curl http://localhost:8000/metrics
```

## Добавление нового провайдера

1. Создайте файл `src/search_service/providers/my_products.py`:

```python
from search_service.providers.sql_base import SQLProviderBase
from search_service.dto.product import ProductDTO

class MyProductsProvider(SQLProviderBase):
    def source_key(self) -> str:
        return "my_products"

    def _pk_column(self) -> str:
        return "id"

    def _table_name(self) -> str:
        return "my_products_table"

    def map_row_to_dto(self, row) -> ProductDTO:
        return ProductDTO(
            source_key=self.source_key(),
            source_id=str(row.id),
            name=row.title,
            price=float(row.price),
            category=row.category_name,
        )

    async def find_one(self, source_id: str) -> ProductDTO | None:
        from sqlalchemy import text
        async with self._session_maker() as session:
            result = await session.execute(
                text("SELECT * FROM my_products_table WHERE id = :id")
                .bindparams(id=int(source_id))
            )
            row = result.fetchone()
            return self.map_row_to_dto(row) if row else None
```

2. Добавьте в `.env`:
```
PROVIDERS_CLASSES=search_service.providers.my_products.MyProductsProvider
```

3. Перезапустите сервис и запустите переиндексацию:
```bash
python -m search_service.cli reindex --source my_products
```

## Деплой через systemd

```bash
# Скопировать юниты (замените /opt/search-service на ваш путь если нужно)
sudo cp deploy/systemd/*.service /etc/systemd/system/

# Отредактируйте WorkingDirectory и EnvironmentFile в .service-файлах
# под ваш реальный путь к проекту

sudo systemctl daemon-reload
sudo systemctl enable --now search-api search-worker
```

## Troubleshooting

**Модели не загружаются**
- Убедитесь, что есть доступ к HuggingFace Hub при первом запуске (модели кешируются в `~/.cache/huggingface/`)
- Проверьте достаточно ли RAM: bge-m3 требует ~2.5 GB, bge-reranker-v2-m3 ~1 GB на CPU
- Установите переменную `HF_HUB_OFFLINE=1` после первой загрузки для работы без интернета

**Qdrant недоступен**
```bash
docker compose ps          # проверить статус контейнера
docker compose logs qdrant # посмотреть логи
curl http://localhost:6333/collections  # проверить API
```

**OOM (Out of Memory)**
- На CPU FP16 недоступен, установите `EMBEDDING_USE_FP16=false`
- Уменьшите `INDEXING_CHUNK_SIZE` до 32-64
- При переиндексации запускайте по одному источнику: `reindex --source KEY`

**MySQL: слишком много соединений**
- Увеличьте `max_connections` в MySQL или добавьте параметр пула в `MYSQL_DSN`:
  `mysql+aiomysql://user:pass@host/db?pool_size=5&max_overflow=10`
