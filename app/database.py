"""Database engine, session factory, and FastAPI dependency.

Two session entry-points are provided:

* ``get_db`` — async generator for FastAPI dependency injection; auto-commits
  on success and rolls back on exception.
* ``AsyncSessionFactory`` — used directly by Temporal activities, which run
  outside the FastAPI request lifecycle and have no access to ``Depends``.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=not settings.is_production,
    pool_size=10,
    max_overflow=20,
)
"""Shared async SQLAlchemy engine. SQL echo is disabled in production."""

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)
"""Session factory used by Temporal activities.

``expire_on_commit=False`` prevents lazy-load errors after a commit when the
session has already been closed.
"""


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a transactional database session.

    Commits the session when the request completes successfully, and rolls
    back automatically if an exception is raised.

    Yields:
        An open ``AsyncSession`` bound to the shared engine.

    Raises:
        Exception: Re-raises any exception after performing a rollback.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
