"""SQLAlchemy engine + session helpers for the CryoET catalog.

``init_schema(engine)`` creates the ORM tables directly via
``Base.metadata.create_all`` for now — Alembic is wired up (see
``catalog/migrations/``) but deferred until production, when the
first real revision will be needed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_URL = "sqlite:///catalog.db"


def make_engine(url: str = DEFAULT_DB_URL) -> Engine:
    """Create a SQLAlchemy engine. Accepts any URL — sqlite:// or postgresql://."""
    return create_engine(url, future=True)


def init_schema(engine: Engine) -> None:
    """Create every ORM-declared table on ``engine`` if it isn't there.

    Pre-production shortcut: no Alembic, no migration history. When prod
    arrives, switch this back to ``alembic upgrade head`` and add the
    first revision under ``catalog/migrations/versions/``.
    """
    # Local import keeps this module light when only ``make_engine`` /
    # ``session_scope`` are needed (e.g. by callers that don't bootstrap
    # the schema themselves).
    from catalog.orm import Base

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
