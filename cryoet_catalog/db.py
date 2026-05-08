"""SQLAlchemy engine + session helpers for the CryoET catalog."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_URL = "sqlite:///cryoet_catalog.db"


def make_engine(url: str = DEFAULT_DB_URL) -> Engine:
    """Create a SQLAlchemy engine. Accepts any URL — sqlite:// or postgresql://."""
    return create_engine(url, future=True)


def init_schema(engine: Engine) -> None:
    """Create all tables defined on the ORM metadata. Idempotent (create_all)."""
    from cryoet_catalog.orm import Base

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a session inside a transaction.

    Commits on clean exit, rolls back on exception, and always closes.
    """
    SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
