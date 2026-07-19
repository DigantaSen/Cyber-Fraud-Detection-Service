"""
Auth Service — Database Connection Pool
Uses asyncpg directly for connection pool management.
SQLAlchemy async engine for ORM operations.
Pool: min=5, max=20 (per Execution.md T5a spec).
"""
from typing import AsyncGenerator

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from fastapi import Depends, Request

from config import settings


def get_engine():
    """Create SQLAlchemy async engine. Called once at startup."""
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=5,
        max_overflow=15,        # 5 + 15 = 20 max total connections
        pool_pre_ping=True,     # Validate connections before use
        echo=False,
    )


def get_session_factory(engine) -> async_sessionmaker:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
