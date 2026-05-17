from __future__ import annotations

from pydantic import BaseModel, Field

from search_service.dto.product import ProductDTO


class FilterSpec(BaseModel):
    category: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    source_keys: list[str] | None = None


class SearchRequest(BaseModel):
    query: str
    filters: FilterSpec | None = None
    limit: int = Field(default=10, ge=1, le=100)
    hydrate_from_db: bool = False
    use_reranker: bool = True
    use_query_parser: bool = False


class ParsedQuery(BaseModel):
    original_query: str
    query: str
    price_min: float | None = None
    price_max: float | None = None
    category: str | None = None
    exclude: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    global_id: str
    score: float
    product: ProductDTO | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    took_ms: float
    reranked: bool
    parsed_query: ParsedQuery | None = None
