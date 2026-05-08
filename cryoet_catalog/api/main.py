"""FastAPI app factory for the catalog read-only API.

The API runs separately from the scanner (the scanner writes; the API reads).
Configuration via environment:
  CATALOG_DB_URL   — SQLAlchemy URL (default: sqlite:///cryoet_catalog.db)
  CORS_ORIGINS     — comma-separated allowed origins (default: http://localhost:5173)
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cryoet_catalog import db
from cryoet_catalog.api.routes import samples, scans, warnings as warnings_routes, extras


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Tests may pre-seed app.state.engine to bypass DB URL config; respect that.
    pre_seeded = getattr(app.state, "engine", None) is not None
    if not pre_seeded:
        db_url = os.environ.get("CATALOG_DB_URL", db.DEFAULT_DB_URL)
        engine = db.make_engine(db_url)
        db.init_schema(engine)  # idempotent; safe on existing DB
        app.state.engine = engine
    yield
    if not pre_seeded:
        app.state.engine.dispose()


def create_app() -> FastAPI:
    cors_origins = _parse_origins(os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    app = FastAPI(title="CryoET Catalog API", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(samples.router, prefix="/samples", tags=["samples"])
    app.include_router(scans.router, prefix="/scans", tags=["scans"])
    app.include_router(warnings_routes.router, prefix="/samples", tags=["warnings"])
    app.include_router(extras.router, prefix="/extras", tags=["extras"])
    return app


app = create_app()
