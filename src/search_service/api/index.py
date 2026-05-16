from __future__ import annotations

import json
import uuid
from typing import Annotated

import arq
import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from search_service.auth import require_auth
from search_service.config import Settings, get_settings
from search_service.deps import (
    get_embedder,
    get_qdrant_store,
    get_redis,
    get_registry,
)
from search_service.dto.indexing import IndexProductRequest, JobStatus, ReindexRequest
from search_service.embedding.bge import BGEM3Embedder
from search_service.indexing.service import IndexingService
from search_service.indexing.tasks import PROGRESS_KEY_PREFIX, WorkerSettings
from search_service.providers.registry import ProviderRegistry
from search_service.vector_store.qdrant import QdrantStore

import redis.asyncio as aioredis

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/index", tags=["index"], dependencies=[Depends(require_auth)])


@router.post("/reindex")
async def reindex(
    req: ReindexRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:  # type: ignore[type-arg]
    job_id = str(uuid.uuid4())
    pool = await arq.create_pool(WorkerSettings.redis_settings())
    if req.source_keys:
        for sk in req.source_keys:
            await pool.enqueue_job("reindex_source_task", sk, req.recreate_collection, job_id)
    else:
        await pool.enqueue_job("reindex_all_task", req.recreate_collection, job_id)
    await pool.aclose()
    return {"job_id": job_id}


@router.post("/product")
async def index_product(
    req: IndexProductRequest,
    embedder: Annotated[BGEM3Embedder, Depends(get_embedder)],
    vector_store: Annotated[QdrantStore, Depends(get_qdrant_store)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:  # type: ignore[type-arg]
    svc = IndexingService(
        embedder=embedder,
        vector_store=vector_store,
        registry=registry,
        chunk_size=settings.indexing_chunk_size,
    )
    await svc.index_one(req.source_key, req.source_id)
    return {"status": "ok", "global_id": f"{req.source_key}:{req.source_id}"}


@router.delete("/product/{global_id}")
async def delete_product(
    global_id: str,
    vector_store: Annotated[QdrantStore, Depends(get_qdrant_store)],
) -> dict:  # type: ignore[type-arg]
    await vector_store.delete([global_id])
    return {"status": "ok", "global_id": global_id}


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    redis: Annotated[aioredis.Redis, Depends(get_redis)],  # type: ignore[type-arg]
) -> JobStatus:
    raw = await redis.get(PROGRESS_KEY_PREFIX + job_id)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    data = json.loads(raw)
    return JobStatus(
        job_id=job_id,
        status=data.get("status", "unknown"),
        progress=data.get("processed", 0),
        total=data.get("total", 0),
    )
