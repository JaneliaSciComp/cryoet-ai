"""FastAPI app factory for the catalog read-only API.

The API runs separately from the scanner (the scanner writes; the API reads).
Configuration via environment:
  CATALOG_DB_URL    — SQLAlchemy URL (default: sqlite:///cryoet_catalog.db)
  CORS_ORIGINS      — comma-separated allowed origins (default: http://localhost:5173)
  CATALOG_DATA_ROOT — filesystem root that bounds all preview/Neuroglancer reads.
                      Required at startup; the API refuses to start without it.
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Eager-import matplotlib so the first preview render doesn't pay the import
# cost. We never use the pyplot global state path — the polar/preview routes
# build figures via the OO API (`Figure(); FigureCanvasAgg`).
try:  # pragma: no cover — environments without matplotlib (e.g. catalog-only) skip.
    import matplotlib  # noqa: F401
    import matplotlib.figure  # noqa: F401
except ModuleNotFoundError:
    pass

from cryoet_catalog import db
from cryoet_catalog.api.routes import samples, scans, warnings as warnings_routes, extras


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


def _detect_multi_worker() -> int | None:
    """Best-effort multi-worker detection from environment signals.

    Returns the worker count if it can be determined and is >1; otherwise None.
    Uvicorn and gunicorn don't expose the worker count to the app process, but
    operators commonly export ``UVICORN_WORKERS`` / ``WEB_CONCURRENCY`` /
    ``GUNICORN_CMD_ARGS=--workers=N``. We sniff those.
    """
    for var in ("UVICORN_WORKERS", "WEB_CONCURRENCY"):
        raw = os.environ.get(var)
        if raw and raw.isdigit() and int(raw) > 1:
            return int(raw)
    return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Tests may pre-seed app.state.engine to bypass DB URL config; respect that.
    pre_seeded_engine = getattr(app.state, "engine", None) is not None
    if not pre_seeded_engine:
        db_url = os.environ.get("CATALOG_DB_URL", db.DEFAULT_DB_URL)
        engine = db.make_engine(db_url)
        db.init_schema(engine)  # idempotent; safe on existing DB
        app.state.engine = engine

    # CATALOG_DATA_ROOT is required for preview/Neuroglancer routes. Tests may
    # pre-seed app.state.data_root_resolved to avoid needing a real directory.
    pre_seeded_root = getattr(app.state, "data_root_resolved", None) is not None
    if not pre_seeded_root:
        raw_root = os.environ.get("CATALOG_DATA_ROOT")
        if not raw_root:
            raise RuntimeError(
                "CATALOG_DATA_ROOT is required (filesystem root bounding all "
                "preview/Neuroglancer reads). Set it to the dir under which "
                "all DB-recorded paths live."
            )
        try:
            resolved = Path(raw_root).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                f"CATALOG_DATA_ROOT={raw_root!r} does not exist or is unreadable"
            ) from exc
        if not resolved.is_dir():
            raise RuntimeError(f"CATALOG_DATA_ROOT={raw_root!r} is not a directory")
        app.state.data_root_resolved = resolved

    workers = _detect_multi_worker()
    if workers is not None:
        logger.warning(
            "Detected {} API workers via env. Neuroglancer binds an HTTP server "
            "once per process; multi-worker breaks viewer launches. Run with "
            "`--workers 1 --no-reload` for the dashboard MVP.",
            workers,
        )

    yield
    if not pre_seeded_engine:
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
