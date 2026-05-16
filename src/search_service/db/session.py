from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@lru_cache(maxsize=1)
def get_session_maker(dsn: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(dsn, pool_pre_ping=True, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)
