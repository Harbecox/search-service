from __future__ import annotations

from fastapi import FastAPI

from search_service.api import health, index, search, sources
from search_service.config import get_settings
from search_service.deps import lifespan
from search_service.logging_setup import configure_logging

settings = get_settings()
configure_logging(settings.app_env, settings.log_level)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(search.router)
app.include_router(index.router)
app.include_router(sources.router)
app.include_router(health.router)
