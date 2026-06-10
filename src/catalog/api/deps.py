"""FastAPI dependencies."""
from __future__ import annotations
from typing import Iterator
from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Iterator[Session]:
    """Yield a SQLAlchemy session bound to the engine stored on app.state.

    Read-only API: we use a plain session (no begin()), commit nothing, close
    on yield exit. The engine is initialized in the lifespan handler.
    """
    engine = request.app.state.engine
    SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
