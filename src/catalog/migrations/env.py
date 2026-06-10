"""Alembic environment for the CryoET catalog.

`target_metadata` is `catalog.orm.Base.metadata` so autogenerate sees
the ORM. `render_as_batch=True` is mandatory for SQLite (ALTER TABLE there
goes through batch table-rebuild). `compare_type=True` so column-type
changes are detected by autogenerate.

The DB URL is sourced from `CATALOG_DB_URL` (or the engine's URL passed in
programmatically via `attributes['connection']`) and falls back to
`catalog.db.DEFAULT_DB_URL`. The `sqlalchemy.url` value in
`alembic.ini` is intentionally empty.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Set up Alembic config + logging.
config = context.config
# Skip fileConfig when invoked programmatically (init_schema passes an
# engine via cfg.attributes['connection']). The ini's [loggers]/[handlers]
# sections install a fresh StreamHandler(sys.stderr) on the root logger
# every call — which clobbers the loguru intercept the API installs at
# lifespan startup. CLI invocations (`pixi run migrate`) still get the
# pretty alembic console formatting.
_programmatic = config.attributes.get("connection") is not None
if config.config_file_name is not None and not _programmatic:
    fileConfig(config.config_file_name)

# Wire ORM metadata for autogenerate. Imported here (not at module top) to
# keep `alembic --help` cheap and to make import errors surface only when
# alembic actually runs.
from catalog.db import DEFAULT_DB_URL  # noqa: E402
from catalog.orm import Base  # noqa: E402

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Pick the DB URL, preferring (in order):

    1. an Alembic config attribute `connection`-derived URL (used when
       `init_schema` calls `command.upgrade(cfg)` against a live engine),
    2. the `CATALOG_DB_URL` environment variable,
    3. `sqlalchemy.url` from alembic.ini,
    4. `catalog.db.DEFAULT_DB_URL`.
    """
    env_url = os.environ.get("CATALOG_DB_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    return DEFAULT_DB_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DB connection)."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live connection).

    Programmatic callers (e.g. ``catalog.db.init_schema``) may pass
    an existing connection via ``cfg.attributes["connection"]``; otherwise
    we build a fresh engine from the resolved URL.
    """
    connectable = config.attributes.get("connection")

    if connectable is None:
        cfg_section = config.get_section(config.config_ini_section, {}) or {}
        cfg_section["sqlalchemy.url"] = _resolve_url()
        connectable = engine_from_config(
            cfg_section,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    else:
        # Already a Connection.
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
