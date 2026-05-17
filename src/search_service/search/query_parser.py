from __future__ import annotations

import json
import re

import httpx
import structlog

from search_service.dto.search import ParsedQuery

log = structlog.get_logger(__name__)

_HAS_NEGATION = re.compile(r'\b(не|без|кроме)\b', re.IGNORECASE)
_PRICE_PATTERN = re.compile(
    r'\s*(?:от|до)\s+\d[\d\s]*(?:[.,]\d+)?\s*(?:руб(?:лей|ля)?\.?|р\.?|₽)?\s*',
    re.IGNORECASE,
)
_EXCLUDE_PATTERN = re.compile(r'\s*(?:не|без|кроме)\s+\S+', re.IGNORECASE)


class OllamaQueryParser:
    def __init__(self, base_url: str, model: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def parse(self, query: str) -> ParsedQuery:
        try:
            response_text = await self._stream_response(query)
            data = json.loads(response_text)

            clean_query = str(data.get("query") or query).strip() or query
            price_min = _to_float(data.get("price_min"))
            price_max = _to_float(data.get("price_max"))

            # Защита от путаницы min/max у маленькой модели:
            # если в оригинале нет "от X" но есть price_min → это на самом деле price_max
            has_price_from = bool(re.search(r'\bот\s+\d', query, re.IGNORECASE))
            has_price_to = bool(re.search(r'\bдо\s+\d', query, re.IGNORECASE))
            if not has_price_from and has_price_to and price_min is not None and price_max is None:
                price_min, price_max = None, price_min

            # Принять exclude только если в оригинале есть явные маркеры отрицания
            has_negation = bool(_HAS_NEGATION.search(query))
            exclude = [str(e) for e in data.get("exclude", []) if e] if has_negation else []

            # Очистить query от ценовых паттернов если модель не очистила
            if price_min or price_max:
                clean_query = _PRICE_PATTERN.sub(' ', clean_query).strip()

            # Очистить query от паттернов исключений
            if exclude:
                clean_query = _EXCLUDE_PATTERN.sub('', clean_query).strip()

            # Нормализовать пробелы
            clean_query = re.sub(r'\s{2,}', ' ', clean_query).strip()

            parsed = ParsedQuery(
                original_query=query,
                query=clean_query or query,
                price_min=price_min,
                price_max=price_max,
                exclude=exclude,
                include=[str(e) for e in data.get("include", []) if e],
                brand=data.get("brand") or None,
                country=data.get("country") or None,
                amps=_to_float(data.get("amps")),
            )
            log.info("query_parsed", original=query, parsed=parsed.model_dump())
            return parsed

        except Exception as exc:
            log.warning("query_parser_failed", error=str(exc), query=query)
            return ParsedQuery(original_query=query, query=query)

    async def _stream_response(self, query: str) -> str:
        result = ""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "stream": True,
                    "format": "json",
                    "prompt": query,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if token:
                        result += token
                    if chunk.get("done"):
                        break
        return result.strip()


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
