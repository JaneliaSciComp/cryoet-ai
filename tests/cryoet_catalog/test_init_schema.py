"""End-to-end tests for ``cryoet_catalog.db.init_schema``.

Pre-production, ``init_schema`` runs ``Base.metadata.create_all`` directly
(see ``cryoet_catalog/migrations/README.md`` for the rationale and the path
back to Alembic when production lands). These tests pin that contract.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from pathlib import Path  # noqa: E402

from sqlalchemy import inspect  # noqa: E402

from cryoet_catalog import db  # noqa: E402
from cryoet_catalog.orm import Base  # noqa: E402


def _engine_at(tmp_path: Path, name: str = "cat.db"):
    return db.make_engine(f"sqlite:///{tmp_path / name}")


def test_init_schema_creates_all_orm_tables(tmp_path):
    engine = _engine_at(tmp_path)
    db.init_schema(engine)

    tables = set(inspect(engine).get_table_names())
    # Every ORM-declared table must be present.
    expected = set(Base.metadata.tables.keys())
    assert expected <= tables, f"missing tables: {expected - tables}"

    # No Alembic version table is written — migrations are deferred.
    assert "alembic_version" not in tables


def test_init_schema_is_idempotent(tmp_path):
    engine = _engine_at(tmp_path)
    db.init_schema(engine)

    pre_tables = set(inspect(engine).get_table_names())

    # Re-run init_schema; create_all is a no-op when every table already exists.
    db.init_schema(engine)

    assert set(inspect(engine).get_table_names()) == pre_tables
