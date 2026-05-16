from __future__ import annotations

from pydantic import BaseModel


class ReindexRequest(BaseModel):
    source_keys: list[str] | None = None
    recreate_collection: bool = False


class IndexProductRequest(BaseModel):
    source_key: str
    source_id: str
    refetch_from_db: bool = True


class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: int = 0
    total: int = 0
