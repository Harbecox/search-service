from __future__ import annotations

import json
import re

import httpx
import structlog

from search_service.dto.search import ParsedQuery

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """Ты парсер поисковых запросов для интернет-магазина.
Извлеки структурированные данные из запроса пользователя.
Верни ТОЛЬКО валидный JSON без пояснений.

Поля:
- query: string — основной поисковый запрос (без упоминания цены и фильтров)
- price_min: number или null — минимальная цена если указана
- price_max: number или null — максимальная цена если указана
- category: string или null — категория товара если явно указана
- exclude: array of strings — что исключить (из "не X", "без X", "кроме X")

Примеры:
Запрос: "хочу дрель до 5000₽, но не ударную и не китайскую"
Ответ: {"query": "дрель", "price_min": null, "price_max": 5000, "category": null, "exclude": ["ударная", "китайская"]}

Запрос: "автоматический выключатель 16А от 500 до 2000 рублей"
Ответ: {"query": "автоматический выключатель 16А", "price_min": 500, "price_max": 2000, "category": null, "exclude": []}

Запрос: "розетка уличная без заземления"
Ответ: {"query": "розетка уличная", "price_min": null, "price_max": null, "category": null, "exclude": ["заземление"]}

Запрос: "болт М6"
Ответ: {"query": "болт М6", "price_min": null, "price_max": null, "category": null, "exclude": []}"""


class OllamaQueryParser:
    def __init__(self, base_url: str, model: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def parse(self, query: str) -> ParsedQuery:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "stream": False,
                        "format": "json",
                        "messages": [
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": query},
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["message"]["content"]
                data = json.loads(content)

            parsed = ParsedQuery(
                original_query=query,
                query=str(data.get("query") or query).strip() or query,
                price_min=_to_float(data.get("price_min")),
                price_max=_to_float(data.get("price_max")),
                category=data.get("category") or None,
                exclude=[str(e).lower() for e in data.get("exclude", []) if e],
            )
            log.info("query_parsed", original=query, parsed=parsed.model_dump())
            return parsed

        except Exception as exc:
            log.warning("query_parser_failed", error=str(exc), query=query)
            return ParsedQuery(original_query=query, query=query)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
