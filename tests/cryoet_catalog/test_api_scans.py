"""Tests for ``/scans`` read-only endpoints (plan §7.6)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from cryoet_catalog import db, orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.main import create_app


# Fixed reference times so ordering assertions are deterministic.
_NOW = 1_700_000_000.0
_T_COMPLETED_START = _NOW - 300.0
_T_COMPLETED_END = _NOW - 250.0
_T_FAILED_START = _NOW - 200.0
_T_FAILED_END = _NOW - 180.0
_T_RUNNING_START = _NOW - 10.0


@pytest.fixture
def client(tmp_path):
    # Temp-file SQLite so multiple sessions share state (mirrors test_api.py).
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    # Bypass lifespan engine setup — store directly. No data_root_resolved
    # needed because TestClient(app) without `with` does not run lifespan.
    app.state.engine = engine

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    # Seed three scans covering the status matrix.
    s = Session()
    try:
        s.add(orm.ScansORM(
            scan_run_id="run-completed",
            started_at=_T_COMPLETED_START,
            ended_at=_T_COMPLETED_END,
            root="/data",
            status="completed",
            samples_upserted=5,
            samples_skipped=1,
            samples_failed=0,
        ))
        s.add(orm.ScansORM(
            scan_run_id="run-failed",
            started_at=_T_FAILED_START,
            ended_at=_T_FAILED_END,
            root="/data",
            status="failed",
            samples_upserted=2,
            samples_skipped=0,
            samples_failed=3,
        ))
        s.add(orm.ScansORM(
            scan_run_id="run-running",
            started_at=_T_RUNNING_START,
            ended_at=None,
            root="/data",
            status="running",
            samples_upserted=None,
            samples_skipped=None,
            samples_failed=None,
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


# ── GET /scans ────────────────────────────────────────────────────────────


def test_list_scans_descending_by_start(client):
    r = client.get("/scans")
    assert r.status_code == 200
    ids = [row["scan_run_id"] for row in r.json()]
    # Most recent started_at first.
    assert ids == ["run-running", "run-failed", "run-completed"]


# ── GET /scans/{scan_run_id} ──────────────────────────────────────────────


def test_get_scan_by_id_returns_full_payload(client):
    r = client.get("/scans/run-completed")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "scan_run_id": "run-completed",
        "started_at": _T_COMPLETED_START,
        "ended_at": _T_COMPLETED_END,
        "root": "/data",
        "status": "completed",
        "samples_upserted": 5,
        "samples_skipped": 1,
        "samples_failed": 0,
    }


def test_get_scan_by_id_failed_status_with_counters(client):
    r = client.get("/scans/run-failed")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["samples_upserted"] == 2
    assert body["samples_skipped"] == 0
    assert body["samples_failed"] == 3
    assert body["ended_at"] == _T_FAILED_END


def test_get_scan_by_id_404_for_unknown(client):
    r = client.get("/scans/does-not-exist")
    assert r.status_code == 404


def test_get_scan_running_serializes_with_none_fields(client):
    # Regression: ScanOut accepts None for ended_at + the three counter fields,
    # and JSON serialization preserves them as explicit nulls.
    r = client.get("/scans/run-running")
    assert r.status_code == 200
    body = r.json()
    assert body["scan_run_id"] == "run-running"
    assert body["status"] == "running"
    assert body["ended_at"] is None
    assert body["samples_upserted"] is None
    assert body["samples_skipped"] is None
    assert body["samples_failed"] is None
    # All keys must be present even when null (so the frontend can rely on the
    # shape without optional-property gymnastics).
    for key in ("ended_at", "samples_upserted", "samples_skipped", "samples_failed"):
        assert key in body


# ── GET /scans/latest (regression — must still resolve before /{id}) ──────


def test_get_latest_completed_still_routes(client):
    r = client.get("/scans/latest")
    assert r.status_code == 200
    body = r.json()
    # Only one completed scan; ``/latest`` must NOT be swallowed by the new
    # ``/{scan_run_id}`` path-param route.
    assert body["scan_run_id"] == "run-completed"
    assert body["status"] == "completed"
