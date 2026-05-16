from __future__ import annotations

import torch
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _auto_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # Application
    app_name: str = "search-service"
    app_env: str = "dev"
    log_level: str = "INFO"

    # Auth
    api_bearer_token: str

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "products"
    qdrant_vector_size: int = 1024

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MySQL
    mysql_dsn: str

    # Embedding
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_device: str = Field(default_factory=_auto_device)
    embedding_use_fp16: bool = True

    # Reranker
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = Field(default_factory=_auto_device)

    # Indexing
    indexing_chunk_size: int = 128
    indexing_queue: str = "search-indexing"

    # Search
    search_top_k_vector: int = 50
    search_top_k_final: int = 10
    search_rerank_threshold: int = 10

    # Cache
    cache_query_embedding_ttl: int = 3600

    # Providers: comma-separated dotted-path class names
    providers_classes: str = ""


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
