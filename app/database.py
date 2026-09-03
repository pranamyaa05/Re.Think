"""
Async database engine and session management.

Key design decisions:
- async engine via asyncpg (non-blocking I/O for FastAPI)
- session factory produces scoped sessions via async context manager
- expire_on_commit=False so objects are usable after commit without re-querying
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ── Engine ────────────────────────────────────────────────────────────────
# pool_pre_ping=True helps detect closed connections across different async contexts
engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=2,
    pool_pre_ping=True,
    echo=False,
)

# ── Session factory ───────────────────────────────────────────────────────
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base model ────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """All ORM models inherit from this."""
    pass


# ── Dependency for FastAPI ────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.
    Commits on success, rolls back on exception, always closes.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
