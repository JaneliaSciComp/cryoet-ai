"""Tests for ``/scans`` read-only endpoints (plan §7.6)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db, orm
from catalog.api.deps import get_session
from catalog.api.main import create_app
from schema.schema import DataSource, Project


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

        # Two samples that exist in the catalog, referenced by the completed
        # scan's membership + warnings.
        s.add(orm.SampleORM(
            sample_id="sample-1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
            type="type-a",
        ))
        s.add(orm.SampleORM(
            sample_id="sample-2",
            data_source=DataSource.experimental,
            project=Project.chromatin,
            type="type-b",
        ))

        # Warnings for the completed scan: sample-1 has 3, sample-2 has 5.
        for i in range(3):
            s.add(orm.ScanWarningsORM(
                sample_id="sample-1", category="cat", location="loc",
                message=f"sample-1 warning {i + 1}",
                detected_at=_T_COMPLETED_END, scan_run_id="run-completed",
            ))
        for i in range(5):
            s.add(orm.ScanWarningsORM(
                sample_id="sample-2", category="cat", location="loc",
                message=f"sample-2 warning {i + 1}",
                detected_at=_T_COMPLETED_END, scan_run_id="run-completed",
            ))

        # Per-sample membership for the completed scan.
        s.add(orm.ScanSamplesORM(
            scan_run_id="run-completed", sample_id="sample-2",
            outcome="upserted",
        ))
        s.add(orm.ScanSamplesORM(
            scan_run_id="run-completed", sample_id="sample-1",
            outcome="skipped",
        ))
        s.add(orm.ScanSamplesORM(
            scan_run_id="run-completed", sample_id="ghost-sample",
            outcome="failed", detail="assemble failed: bad metadata",
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


# ── GET /scans/latest/warnings ────────────────────────────────────────────


def test_latest_warnings_grouped_by_sample(client):
    r = client.get("/scans/latest/warnings")
    assert r.status_code == 200
    body = r.json()
    by_sample = {g["sample_id"]: g["warnings"] for g in body}
    assert set(by_sample) == {"sample-1", "sample-2"}
    assert by_sample["sample-1"] == [
        "sample-1 warning 1",
        "sample-1 warning 2",
        "sample-1 warning 3",
    ]
    assert len(by_sample["sample-2"]) == 5


def test_latest_warnings_must_route_before_id(client):
    # Regression: ``/latest/warnings`` must not be swallowed by ``/{scan_run_id}``.
    r = client.get("/scans/latest/warnings")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── GET /scans/latest/samples ─────────────────────────────────────────────


def test_latest_samples_upserted_joins_metadata(client):
    r = client.get("/scans/latest/samples", params={"outcome": "upserted"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["sample_id"] == "sample-2"
    assert row["data_source"] == "experimental"
    assert row["project"] == "chromatin"
    assert row["type"] == "type-b"
    assert row["warning_count"] == 5
    assert row["detail"] is None


def test_latest_samples_skipped(client):
    r = client.get("/scans/latest/samples", params={"outcome": "skipped"})
    assert r.status_code == 200
    body = r.json()
    assert [row["sample_id"] for row in body] == ["sample-1"]
    assert body[0]["warning_count"] == 3


def test_latest_samples_failed_has_detail_and_null_metadata(client):
    r = client.get("/scans/latest/samples", params={"outcome": "failed"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    # Failed sample was never persisted — metadata null, error in detail.
    assert row["sample_id"] == "ghost-sample"
    assert row["data_source"] is None
    assert row["project"] is None
    assert row["warning_count"] == 0
    assert row["detail"] == "assemble failed: bad metadata"


def test_latest_samples_rejects_unknown_outcome(client):
    r = client.get("/scans/latest/samples", params={"outcome": "bogus"})
    assert r.status_code == 422


# ── GET /scans/{scan_run_id}/warnings ─────────────────────────────────────


def test_scan_warnings_by_id_grouped_by_sample(client):
    r = client.get("/scans/run-completed/warnings")
    assert r.status_code == 200
    by_sample = {g["sample_id"]: g["warnings"] for g in r.json()}
    assert set(by_sample) == {"sample-1", "sample-2"}
    assert by_sample["sample-1"] == [
        "sample-1 warning 1",
        "sample-1 warning 2",
        "sample-1 warning 3",
    ]
    assert len(by_sample["sample-2"]) == 5


def test_scan_warnings_by_id_empty_for_scan_without_warnings(client):
    # ``run-failed`` recorded no warnings — an empty list, not a 404.
    r = client.get("/scans/run-failed/warnings")
    assert r.status_code == 200
    assert r.json() == []


def test_scan_warnings_by_id_404_for_unknown(client):
    r = client.get("/scans/does-not-exist/warnings")
    assert r.status_code == 404


# ── GET /scans/{scan_run_id}/samples ──────────────────────────────────────


def test_scan_samples_by_id_upserted_joins_metadata(client):
    r = client.get("/scans/run-completed/samples", params={"outcome": "upserted"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["sample_id"] == "sample-2"
    assert row["data_source"] == "experimental"
    assert row["project"] == "chromatin"
    assert row["type"] == "type-b"
    assert row["warning_count"] == 5
    assert row["detail"] is None


def test_scan_samples_by_id_skipped(client):
    r = client.get("/scans/run-completed/samples", params={"outcome": "skipped"})
    assert r.status_code == 200
    body = r.json()
    assert [row["sample_id"] for row in body] == ["sample-1"]
    assert body[0]["warning_count"] == 3


def test_scan_samples_by_id_failed_has_detail_and_null_metadata(client):
    r = client.get("/scans/run-completed/samples", params={"outcome": "failed"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["sample_id"] == "ghost-sample"
    assert row["data_source"] is None
    assert row["project"] is None
    assert row["warning_count"] == 0
    assert row["detail"] == "assemble failed: bad metadata"


def test_scan_samples_by_id_empty_for_scan_without_membership(client):
    # ``run-failed`` has no scan_samples rows — empty list, not a 404.
    r = client.get("/scans/run-failed/samples", params={"outcome": "upserted"})
    assert r.status_code == 200
    assert r.json() == []


def test_scan_samples_by_id_404_for_unknown(client):
    r = client.get(
        "/scans/does-not-exist/samples", params={"outcome": "upserted"}
    )
    assert r.status_code == 404


def test_scan_samples_by_id_rejects_unknown_outcome(client):
    r = client.get("/scans/run-completed/samples", params={"outcome": "bogus"})
    assert r.status_code == 422
