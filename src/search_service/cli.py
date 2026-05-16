from __future__ import annotations

import asyncio
import sys
import uuid

import structlog

log = structlog.get_logger(__name__)


def _get_deps() -> tuple:
    from search_service.config import get_settings
    from search_service.embedding.bge import BGEM3Embedder
    from search_service.indexing.service import IndexingService
    from search_service.providers.registry import ProviderRegistry
    from search_service.vector_store.qdrant import QdrantStore
    from qdrant_client import AsyncQdrantClient

    settings = get_settings()
    embedder = BGEM3Embedder(
        model_name=settings.embedding_model_name,
        device=settings.embedding_device,
        use_fp16=settings.embedding_use_fp16,
    )
    client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    store = QdrantStore(client=client, settings=settings)
    registry = ProviderRegistry()
    registry.load_from_settings(settings)
    svc = IndexingService(
        embedder=embedder,
        vector_store=store,
        registry=registry,
        chunk_size=settings.indexing_chunk_size,
    )
    return svc, client, settings


async def _init_collection() -> None:
    from search_service.config import get_settings
    from search_service.vector_store.qdrant import QdrantStore
    from qdrant_client import AsyncQdrantClient

    settings = get_settings()
    client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    store = QdrantStore(client=client, settings=settings)
    await store.ensure_collection()
    await client.close()
    print("Collection initialised.")


async def _reindex(source: str | None, fresh: bool) -> None:
    import arq

    from search_service.config import get_settings
    from search_service.indexing.tasks import WorkerSettings

    settings = get_settings()
    job_id = str(uuid.uuid4())
    redis = await arq.create_pool(WorkerSettings.redis_settings)
    if source:
        await redis.enqueue_job("reindex_source_task", source, fresh, job_id)
    else:
        await redis.enqueue_job("reindex_all_task", fresh, job_id)
    await redis.aclose()
    print(f"Enqueued. job_id={job_id}")


def main() -> None:
    from search_service.logging_setup import configure_logging
    from search_service.config import get_settings

    settings = get_settings()
    configure_logging(settings.app_env, settings.log_level)

    args = sys.argv[1:]
    if not args:
        print("Commands: init-collection | reindex [--source KEY] [--fresh] | worker")
        sys.exit(1)

    cmd = args[0]

    if cmd == "init-collection":
        asyncio.run(_init_collection())

    elif cmd == "reindex":
        source: str | None = None
        fresh = False
        i = 1
        while i < len(args):
            if args[i] == "--source" and i + 1 < len(args):
                source = args[i + 1]
                i += 2
            elif args[i] == "--fresh":
                fresh = True
                i += 1
            else:
                i += 1
        asyncio.run(_reindex(source, fresh))

    elif cmd == "worker":
        import subprocess
        subprocess.run(
            ["arq", "search_service.indexing.tasks.WorkerSettings"],
            check=True,
        )

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
