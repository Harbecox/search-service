from __future__ import annotations

import json

import httpx
import structlog

from search_service.dto.search import ParsedQuery

log = structlog.get_logger(__name__)


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

            # Если модель не очистила query от ценового паттерна — чистим сами
            if price_min or price_max:
                import re
                clean_query = re.sub(
                    r'\s*(?:от|до)\s+\d[\d\s]*(?:[.,]\d+)?\s*(?:руб(?:лей|ля)?\.?|р\.?|₽)?\s*',
                    ' ', clean_query, flags=re.IGNORECASE
                ).strip()

            parsed = ParsedQuery(
                original_query=query,
                query=clean_query or query,
                price_min=price_min,
                price_max=price_max,
                category=data.get("category") or None,
                exclude=[str(e).lower() for e in data.get("exclude", []) if e],
            )
            log.info("query_parsed", original=query, parsed=parsed.model_dump())
            return parsed

        except Exception as exc:
            log.warning("query_parser_failed", error=str(exc), query=query)
            return ParsedQuery(original_query=query, query=query)

    async def _stream_response(self, query: str) -> str:
        """Собирает только поле 'response' из стрима, пропуская 'thinking'."""
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
                    # Собираем только 'response', игнорируем 'thinking'
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
