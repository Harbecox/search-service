# Задача: Python-микросервис AI-поиска товаров

## Контекст
- Отдельный сервис на Python, рядом с существующим Laravel-проектом
- Сервер: Ubuntu, есть Docker, Redis уже установлен и работает
- MySQL — источник товаров (несколько таблиц разной структуры), доступ только на чтение
- Клиент — Laravel, ходит по HTTP с Bearer-токеном
- Интерфейса/фронта НЕ делать — только REST API
- Масштаб: 1M+ товаров, расширяемое число источников

## Стек, который ОБЯЗАТЕЛЬНО использовать
- Python 3.11+
- FastAPI + Uvicorn
- Qdrant (Docker) — векторное хранилище
- FlagEmbedding (для BAAI/bge-m3 и BAAI/bge-reranker-v2-m3) — модели грузятся в процесс, БЕЗ отдельного TEI-сервиса
- SQLAlchemy 2.0 (async, через aiomysql или asyncmy)
- Pydantic v2 + pydantic-settings
- ARQ (Redis-based) для очередей
- structlog для логов
- pytest + pytest-asyncio для тестов
- uv как менеджер зависимостей (если недоступен — Poetry)

## Что НЕ делать
- Никаких UI/фронта/Jinja-шаблонов
- Не использовать Celery — только ARQ (async-нативная)
- Не использовать TEI/HuggingFace inference сервер — модели грузим напрямую через FlagEmbedding
- Не писать всё в main.py — следовать структуре проекта ниже
- Не делать синхронную индексацию миллиона товаров в HTTP-запросе — только через очередь
- Не объяснять каждое изменение длинно — работай молча, краткий отчёт в конце каждого этапа

---

## ЭТАП 0: Подготовка
Перед началом задай мне ОДНИМ сообщением:
1. Есть ли GPU на сервере (CUDA)? Если да — какой vRAM?
2. DSN MySQL (или хотя бы хост/порт/база, креды я подставлю в .env сам)
3. Куда класть проект (предложи `/var/www/search-service` или `/opt/search-service`)

После моих ответов начинай ЭТАП 1.

---

## ЭТАП 1: Скелет проекта

Создай структуру:
```
search_service/
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── src/search_service/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── deps.py
│   ├── auth.py
│   ├── logging_setup.py
│   ├── api/
│   ├── dto/
│   ├── providers/
│   ├── embedding/
│   ├── vector_store/
│   ├── reranker/
│   ├── search/
│   ├── indexing/
│   ├── cache/
│   └── db/
└── tests/
    ├── unit/
    └── integration/
```

`pyproject.toml` со всеми зависимостями (uv).
`docker-compose.yml` — qdrant (порты 6333/6334, volume `./data/qdrant`). Redis НЕ добавляй, он уже есть на хосте.
`.gitignore` стандартный для Python + `.env`, `data/`, `__pycache__/`, `.venv/`.

---

## ЭТАП 2: Конфигурация и DI

`config.py` — `Settings(BaseSettings)` из pydantic-settings, читает `.env`:
- `app_name`, `app_env` (dev/prod), `log_level`
- `api_bearer_token` (секрет)
- `qdrant_host`, `qdrant_port`, `qdrant_collection`, `qdrant_vector_size=1024`
- `redis_url`
- `mysql_dsn`
- `embedding_model_name='BAAI/bge-m3'`, `embedding_device` (cuda/cpu, auto-detect)
- `embedding_use_fp16=True`
- `reranker_model_name='BAAI/bge-reranker-v2-m3'`, `reranker_device`
- `indexing_chunk_size=128`, `indexing_queue='search-indexing'`
- `search_top_k_vector=50`, `search_top_k_final=10`, `search_rerank_threshold=10`
- `cache_query_embedding_ttl=3600`

`logging_setup.py` — structlog в JSON для prod, читаемый для dev.

`auth.py` — FastAPI dependency, проверяющий `Authorization: Bearer <token>` против `api_bearer_token`.

`deps.py` — синглтоны/lifespan для embedder, reranker, qdrant client, redis, db session.

---

## ЭТАП 3: DTO

В `dto/`:

`product.py`:
```python
class ProductDTO(BaseModel):
    source_key: str
    source_id: str  # приводи всегда к str для единообразия
    name: str
    description: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    price: float | None = None
    category: str | None = None
    image_url: str | None = None
    meta: dict = Field(default_factory=dict)

    @property
    def global_id(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    def to_embedding_text(self) -> str:
        # Формат: "{name}. Характеристики: k1=v1, k2=v2. {description}"
        # Название важнее всего — повторяем его дважды для веса
        ...
```

`search.py`:
- `FilterSpec(category, price_min, price_max, source_keys)`
- `SearchRequest(query, filters, limit=10, hydrate_from_db=False, use_reranker=True)`
- `SearchHit(global_id, score, product)`
- `SearchResponse(query, hits, took_ms, reranked: bool)`

`indexing.py`:
- `ReindexRequest(source_keys: list[str] | None = None, recreate_collection: bool = False)`
- `IndexProductRequest(source_key, source_id, refetch_from_db: bool = True)` — для инкрементальных обновлений из Laravel
- `JobStatus(job_id, status, progress, total)`

---

## ЭТАП 4: Контракты (Protocols)

В каждой папке (`embedding/base.py`, `vector_store/base.py`, `reranker/base.py`, `providers/base.py`) — `typing.Protocol`:

```python
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

class VectorStore(Protocol):
    async def ensure_collection(self) -> None: ...
    async def upsert(self, points: list[VectorPoint]) -> None: ...
    async def search(self, vector: list[float], filters: FilterSpec | None, limit: int) -> list[SearchCandidate]: ...
    async def delete(self, global_ids: list[str]) -> None: ...
    async def count(self) -> int: ...

class Reranker(Protocol):
    async def rerank(self, query: str, candidates: list[tuple[str, str]], top_k: int) -> list[tuple[str, float]]:
        # candidates = [(global_id, text), ...]
        # return = [(global_id, score), ...] sorted desc
        ...

class ProductProvider(Protocol):
    def source_key(self) -> str: ...
    async def chunked(self, chunk_size: int) -> AsyncIterator[list[ProductDTO]]: ...
    async def find_one(self, source_id: str) -> ProductDTO | None: ...
    async def count(self) -> int: ...
```

Внутренние типы (`VectorPoint`, `SearchCandidate`) — pydantic-модели в тех же модулях.

---

## ЭТАП 5: Имплементации

### `embedding/bge.py` — BGEM3Embedder
- Класс `BGEM3Embedder`, при инициализации грузит `FlagEmbedding.BGEM3FlagModel`
- Параметры: `model_name`, `device`, `use_fp16`
- `embed_batch` — оборачивай блокирующий `.encode()` в `asyncio.to_thread`
- Возвращает только `dense_vecs` (sparse и colbert пока не нужны)
- Нормализация L2 на стороне модели уже есть, ничего не делай дополнительно

### `vector_store/qdrant.py` — QdrantStore
- Использует `qdrant-client[fastembed]` в async-режиме (`AsyncQdrantClient`)
- `ensure_collection` — создаёт коллекцию если её нет, vector size из конфига, distance=COSINE, HNSW параметры по умолчанию
- Payload-индексы создавать для: `source_key` (keyword), `category` (keyword), `price` (float)
- `upsert` — points c id = uuid5 от global_id (Qdrant требует UUID или int), а global_id хранить в payload
- `search` — формирует Qdrant Filter из FilterSpec: `must` для category и source_keys, range для price
- `delete` — по global_id из payload через filter delete

### `reranker/bge.py` — BGERerankerV2
- `FlagEmbedding.FlagReranker` для `BAAI/bge-reranker-v2-m3`
- `compute_score` оборачиваем в `asyncio.to_thread`
- Возвращает топ-K по убыванию score

### `cache/redis_cache.py`
- Простой класс над `redis.asyncio`
- Метод `get_or_set_embedding(query: str, factory: Callable) -> list[float]`
- Ключ: `emb:{sha256(query)}`, TTL из конфига
- Хранить как pickle или msgpack (msgpack компактнее)

### `db/session.py`
- `async_engine` через `create_async_engine(mysql_dsn)`
- `async_session_maker`
- Используется ТОЛЬКО провайдерами

---

## ЭТАП 6: Провайдеры

### `providers/sql_base.py` — SQLProviderBase
Абстрактный класс с готовой реализацией `chunked` через keyset pagination (по PK), чтобы не задыхаться на 1M строк. Подкласс реализует:
- `source_key()`
- `model` (SQLAlchemy модель или явный SELECT)
- `map_row_to_dto(row) -> ProductDTO`
- `find_one(source_id)`

### `providers/example.py` — ExampleProvider
Заглушка с TODO. Демонстрирует как подключить новую таблицу. Я допишу под свои таблицы сам.

### `providers/registry.py` — ProviderRegistry
- `register(provider)`, `get(source_key)`, `all()`
- Регистрация при старте FastAPI через config: список dotted-path классов, импортируются динамически
- Конфиг: `providers_classes: list[str] = []` в Settings

---

## ЭТАП 7: SearchService

`search/service.py`:

```python
class SearchService:
    def __init__(self, embedder, vector_store, reranker, cache, registry, settings):
        ...
    
    async def search(self, req: SearchRequest) -> SearchResponse:
        # 1. Получить embedding запроса (через кеш)
        # 2. vector_store.search с фильтрами, лимит = settings.search_top_k_vector (50)
        # 3. Если len(results) > settings.search_rerank_threshold и req.use_reranker:
        #    reranker.rerank(query, [(gid, payload.text), ...], top_k=req.limit)
        # 4. Если req.hydrate_from_db — подгрузить свежие данные через registry
        # 5. Замерить took_ms, вернуть SearchResponse
```

Текст для re-ranker'а должен быть сохранён в payload Qdrant при индексации (поле `text`) — берётся из `ProductDTO.to_embedding_text()`.

---

## ЭТАП 8: IndexingService и ARQ tasks

### `indexing/service.py` — IndexingService
- `reindex_all(recreate=False)` — пересоздать коллекцию (опционально), пройти по всем провайдерам
- `reindex_source(source_key, recreate=False)`
- `index_one(source_key, source_id)` — для синхронной точечной индексации
- Внутри использует чанкование от провайдеров и батчевый embed

### `indexing/tasks.py` — ARQ tasks
- `WorkerSettings` с redis_settings из конфига
- Задачи: `reindex_all_task`, `reindex_source_task`, `index_chunk_task`
- Прогресс пишется в Redis ключ `arq:progress:{job_id}` = {processed, total}

### CLI-команды (через `python -m search_service.cli`):
- `init-collection` — создать коллекцию в Qdrant
- `reindex [--source KEY] [--fresh]` — запустить полную переиндексацию (диспатчит в ARQ и выводит job_id)
- `worker` — запустить ARQ worker (на самом деле обёртка над `arq search_service.indexing.tasks.WorkerSettings`)

---

## ЭТАП 9: API endpoints

`main.py` — FastAPI app, lifespan для загрузки моделей и инициализации зависимостей, монтирует роутеры из `api/`.

### `api/search.py`
- `POST /search` — требует Bearer auth, принимает SearchRequest, возвращает SearchResponse
- Rate-limit пока не нужен (внутренний сервис), но логировать query, took_ms, count

### `api/index.py`
- `POST /index/reindex` — body: ReindexRequest, ставит задачу в ARQ, возвращает `{job_id}`
- `POST /index/product` — body: IndexProductRequest, индексирует синхронно ОДИН товар (быстро, не нужна очередь)
- `DELETE /index/product/{global_id}` — удаляет из Qdrant
- `GET /index/jobs/{job_id}` — статус задачи из Redis

### `api/sources.py`
- `GET /sources` — список зарегистрированных провайдеров: `[{source_key, count_in_db, count_in_index}]`

### `api/health.py`
- `GET /health` — пинг Qdrant, Redis, MySQL, проверка что модели загружены. 200 если всё ок, 503 иначе
- `GET /metrics` — простая статистика: количество запросов, средний latency, hit-rate кеша (счётчики в Redis)

---

## ЭТАП 10: systemd-юниты

Создай два файла в `deploy/systemd/`:
- `search-api.service` — запускает Uvicorn с `--workers 1` (одна копия модели в памяти, не плодим)
- `search-worker.service` — запускает ARQ worker

Оба с `Restart=always`, `User=www-data` (или другой по моему указанию), путь к проекту переменной.

В README инструкция:
```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now search-api search-worker
```

---

## ЭТАП 11: Тесты

`tests/unit/`:
- `test_product_dto.py` — `to_embedding_text`, `global_id`
- `test_filter_mapping.py` — FilterSpec → Qdrant Filter
- `test_search_service.py` — с моками embedder/store/reranker, проверка флоу (с rerank / без, с гидрацией)

`tests/integration/`:
- `test_qdrant_store.py` — с реальным Qdrant в Docker (testcontainers или docker-compose в CI)
- `test_search_endpoint.py` — TestClient, с моками тяжёлых зависимостей

Не пиши тесты на BGE — это сторонняя библиотека.

---

## ЭТАП 12: README

В README:
1. Что это, краткая архитектура
2. Требования (Python 3.11+, Docker, Redis, MySQL)
3. Установка: `uv sync`, `cp .env.example .env`, `docker compose up -d qdrant`
4. Первый запуск: `python -m search_service.cli init-collection`
5. Запуск API: `uvicorn search_service.main:app --host 0.0.0.0 --port 8000`
6. Запуск воркера: `python -m search_service.cli worker`
7. Примеры curl для каждого endpoint
8. Как добавить новый провайдер (пошагово на примере ExampleProvider)
9. systemd-деплой
10. Раздел Troubleshooting (модели не грузятся, Qdrant недоступен, OOM)

---

## Правила работы
- После каждого этапа — короткий отчёт: что создано, какие команды я должен запустить
- Если возникает развилка (несколько разумных вариантов) — спроси меня
- Используй type hints везде, mypy-чистый код
- `ruff` для линтинга, `ruff format` для форматирования — добавь конфиг в pyproject
- В сервисах НЕ используй глобальные синглтоны напрямую — только через DI (FastAPI Depends или конструктор)
- Не коммить .env, креды, модельные веса
- В конце ВСЕЙ работы — общий отчёт: список созданных файлов, чек-лист ручных действий (env, docker, systemd, первый reindex)

Начни с ЭТАПА 0 — задай мне три вопроса и жди ответов.
