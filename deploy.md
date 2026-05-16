# Деплой search-service на сервер

## Требования к серверу

- Ubuntu 20.04+
- Python 3.11+ (проверено на 3.12)
- Docker + Docker Compose
- Redis (уже запущен)
- MySQL (read-only доступ к таблицам товаров)
- RAM: минимум 6 GB свободных (bge-m3 ~2.5 GB + reranker ~1 GB + OS)
- Диск: ~10 GB (модели + Qdrant данные)

---

## Шаг 0 — Установить зависимости системы

### Python 3.12

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev

# Проверить:
python3.12 --version
```

### Docker + Docker Compose

```bash
# Удалить старые версии если есть:
sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Установить:
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Запустить и включить автозапуск:
sudo systemctl enable --now docker

# Разрешить запуск без sudo (нужно перелогиниться):
sudo usermod -aG docker $USER
newgrp docker

# Проверить:
docker --version
docker compose version
```

### uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Проверить:
uv --version
```

### git (если нужен)

```bash
sudo apt install -y git
```

---

## Шаг 1 — Установить uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv --version
```

---

## Шаг 2 — Скопировать проект на сервер

```bash
# С вашей машины:
rsync -av --exclude='.venv' --exclude='data/' --exclude='__pycache__' \
  /home/harbecox/PycharmProjects/AI_SEARCH/ user@SERVER:/opt/search-service/

# Или через git, если репозиторий настроен:
git clone <repo-url> /opt/search-service
```

---

## Шаг 3 — Установить зависимости

```bash
cd /opt/search-service
uv sync
```

---

## Шаг 4 — Настроить окружение

```bash
cp .env.example .env
nano .env
```

Заполнить обязательно:

```dotenv
APP_ENV=prod
LOG_LEVEL=INFO

# Генерировать: python -c "import secrets; print(secrets.token_urlsafe(32))"
API_BEARER_TOKEN=ВАШ_ТОКЕН

# ВАЖНО: если в пароле есть @ — заменить на %40
# Пример: пароль "abc@123" → "abc%40123"
MYSQL_DSN=mysql+aiomysql://USER:PASS@localhost:3306/DBNAME

REDIS_URL=redis://localhost:6379/0

QDRANT_HOST=localhost
QDRANT_PORT=6333

# CPU-сервер:
EMBEDDING_DEVICE=cpu
EMBEDDING_USE_FP16=false
RERANKER_DEVICE=cpu

# Провайдеры (через запятую):
PROVIDERS_CLASSES=search_service.providers.products.ProductsProvider

# Оптимальные значения для CPU без reranker:
SEARCH_TOP_K_VECTOR=200
SEARCH_TOP_K_FINAL=10
SEARCH_RERANK_THRESHOLD=9999
```

---

## Шаг 5 — Запустить Qdrant

```bash
cd /opt/search-service
docker compose up -d qdrant

# Проверить:
curl http://localhost:6333/collections
```

---

## Шаг 6 — Создать коллекцию в Qdrant

```bash
cd /opt/search-service
python -m search_service.cli init-collection
```

Ожидаемый вывод: `Collection initialised.`

---

## Шаг 7 — Настроить systemd

Отредактировать юниты под ваш путь и пользователя:

```bash
# Заменить /opt/search-service на ваш путь если отличается
sudo nano /opt/search-service/deploy/systemd/search-api.service
sudo nano /opt/search-service/deploy/systemd/search-worker.service
```

В каждом файле проверить:
- `WorkingDirectory=` — путь к проекту
- `EnvironmentFile=` — путь к `.env`
- `ExecStart=` — путь к `.venv/bin/uvicorn` и `.venv/bin/arq`
- `User=` — пользователь (по умолчанию `www-data`)

Установить юниты:

```bash
sudo cp /opt/search-service/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable search-api search-worker
```

---

## Шаг 8 — Первый запуск (загрузка моделей)

При первом запуске модели скачиваются с HuggingFace (~3.5 GB). Сделайте это вручную перед systemd, чтобы видеть прогресс:

```bash
cd /opt/search-service
# Запустить API вручную — дождаться "Application startup complete."
uvicorn search_service.main:app --host 0.0.0.0 --port 8000
# После загрузки моделей — Ctrl+C
```

Модели кешируются в `~/.cache/huggingface/` — повторный запуск будет быстрым.

---

## Шаг 9 — Первая индексация

```bash
# Запустить воркер в фоне
sudo systemctl start search-worker
sudo journalctl -u search-worker -f &   # следить за логами

# Запустить полную индексацию
cd /opt/search-service
python -m search_service.cli reindex

# Следить за прогрессом
# В логах воркера будет: indexing_progress source_key=products processed=128, 256, ...
```

**Ориентировочное время на CPU:** ~2-4 часа на 27K товаров. Оставьте работать.

Проверить сколько проиндексировано:
```bash
curl http://localhost:6333/collections/products | python -m json.tool | grep points_count
```

---

## Шаг 10 — Запустить через systemd

```bash
sudo systemctl start search-api
sudo systemctl start search-worker

# Проверить статус:
sudo systemctl status search-api
sudo systemctl status search-worker

# Логи:
sudo journalctl -u search-api -f
sudo journalctl -u search-worker -f
```

---

## Шаг 11 — Проверить что всё работает

```bash
# Health check:
curl http://localhost:8000/health

# Тестовый поиск:
curl -s -X POST http://localhost:8000/search \
  -H "Authorization: Bearer ВАШ_ТОКЕН" \
  -H "Content-Type: application/json" \
  -d '{"query": "автоматический выключатель", "limit": 5}' | python -m json.tool
```

Ожидаемый результат: `{"query": "...", "hits": [...], "took_ms": <20-50>, "reranked": false}`

---

## Обновление кода

```bash
cd /opt/search-service

# Обновить код
git pull  # или rsync с вашей машины

# Обновить зависимости если изменился pyproject.toml
uv sync

# Перезапустить сервисы
sudo systemctl restart search-api
sudo systemctl restart search-worker
```

---

## Переиндексация после изменения данных

```bash
# Полная переиндексация всех источников:
python -m search_service.cli reindex

# Только один источник:
python -m search_service.cli reindex --source products

# Пересоздать коллекцию с нуля (удалит все данные!):
python -m search_service.cli reindex --fresh

# Один товар (из Laravel после изменения):
curl -X POST http://localhost:8000/index/product \
  -H "Authorization: Bearer ВАШ_ТОКЕН" \
  -H "Content-Type: application/json" \
  -d '{"source_key": "products", "source_id": "123"}'
```

---

## Настройка Nginx (опционально)

Если нужен публичный доступ через Nginx:

```nginx
server {
    listen 80;
    server_name search.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

---

## Troubleshooting

**`SettingsError: error parsing value for field "providers_classes"`**
→ В `.env` оставьте поле пустым (`PROVIDERS_CLASSES=`) или укажите класс без пробелов.

**`Can't connect to MySQL server on 'xxx@localhost'`**
→ В пароле есть `@`. Замените на `%40`. Пример: `pass@word` → `pass%40word`

**`Embedder not initialised` (500 на /search)**
→ Uvicorn не перезапустился после изменений. Сделайте `sudo systemctl restart search-api`.

**Модели не скачиваются (нет интернета на сервере)**
→ Скачайте модели заранее на машине с интернетом:
```bash
python -c "from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3')"
python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; AutoTokenizer.from_pretrained('BAAI/bge-reranker-v2-m3'); AutoModelForSequenceClassification.from_pretrained('BAAI/bge-reranker-v2-m3')"
```
Скопируйте `~/.cache/huggingface/` на сервер.

**OOM (процесс убит)**
→ Проверьте `dmesg | grep -i kill`. Уменьшите `INDEXING_CHUNK_SIZE=32` в `.env`.

**Qdrant недоступен**
```bash
docker compose ps
docker compose logs qdrant
docker compose restart qdrant
```
