"""SQLAlchemy engine + session factory (Postgres = system of record).

Engine/session are created lazily so importing the app doesn't require a live
DB driver or connection — keeps imports cheap and unit tests dependency-light.
"""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().postgres_dsn, pool_pre_ping=True, future=True)


@lru_cache
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
