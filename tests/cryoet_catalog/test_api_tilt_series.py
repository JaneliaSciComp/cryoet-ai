"""Tilt-series preview + polar endpoints (plan §7.5).

Coverage:
    - GET preview.png — zarr path (synthetic ome.zarr) returns PNG
    - GET preview.png — frames-dir fallback returns PNG when zarr absent
    - GET preview.png — 422 when both zarr and mdoc_path are NULL
    - GET preview.png — 422 when frames dir has no viewable images
    - GET polar.png — 200 + PNG when tilt_angles cached
    - GET polar.png — 422 when tilt_angles missing
    - GET polar.png — cache returns identical bytes on second call
    - 404 for unknown tilt_series id / soft-deleted parent
"""
from __future__ import annotations

import time
from pathlib import Path

import mrcfile
import numpy as np
import pytest
import tifffile
import zarr
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from cryoet_catalog import db, orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.main import create_app
from cryoet_schema.schema import DataSource, Project


def _write_zarr_tilt_stack(zarr_path: Path, n: int = 5) -> None:
    """Create an ome.zarr-style store with a ``tilt_series`` dataset + angles attr."""
    root = zarr.open_group(str(zarr_path), mode="w")
    data = np.linspace(0, 100, n * 8 * 8, dtype=np.float32).reshape(n, 8, 8)
    ds = root.create_array("tilt_series", shape=data.shape, dtype=data.dtype, chunks=(1, 8, 8))
    ds[:] = data
    root.update_attributes({"tilt_angles": [-30.0, -15.0, 0.0, 15.0, 30.0][:n]})


def _write_synthetic_tiff(path: Path, name: str) -> None:
    """Write a TIFF named so ``extract_tilt_angle_from_filename`` recovers an angle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.linspace(0, 200, 16 * 16, dtype=np.float32).reshape(16, 16)
    tifffile.imwrite(path / name, img)


def _write_mdoc_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# stub mdoc\n")


@pytest.fixture
def client(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()

    # ts_zarr  — has zarr stack
    zarr_path = data_root / "ts_zarr" / "frames" / "ts1.zarr"
    _write_zarr_tilt_stack(zarr_path)
    mdoc_zarr = data_root / "ts_zarr" / "frames" / "ts1.mdoc"
    _write_mdoc_stub(mdoc_zarr)

    # ts_frames — no zarr, TIFF siblings with embedded angles
    frames_dir = data_root / "ts_frames" / "frames"
    frames_dir.mkdir(parents=True)
    for name in ("scan_001_-30.0.tif", "scan_002_0.0.tif", "scan_003_30.0.tif"):
        tifffile.imwrite(frames_dir / name, np.linspace(0, 200, 16*16, dtype=np.float32).reshape(16, 16))
    mdoc_frames = frames_dir / "scan.mdoc"
    _write_mdoc_stub(mdoc_frames)

    # ts_empty — mdoc_path points at a frames dir with NO viewable images
    empty_dir = data_root / "ts_empty" / "frames"
    empty_dir.mkdir(parents=True)
    mdoc_empty = empty_dir / "stub.mdoc"
    _write_mdoc_stub(mdoc_empty)

    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    app.state.engine = engine
    app.state.data_root_resolved = data_root.resolve()

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    s = Session()
    try:
        s.add(orm.SampleORM(
            sample_id="sample_a", data_source=DataSource.experimental, project=Project.chromatin,
        ))
        s.add(orm.AcquisitionORM(sample_id="sample_a", acquisition_id="acq1"))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_zarr",
            mdoc_path=str(mdoc_zarr), zarr_path=str(zarr_path),
            tilt_angles=[-30.0, -15.0, 0.0, 15.0, 30.0],
            n_tilts=5, mtime=1234567890.0,
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_frames",
            mdoc_path=str(mdoc_frames),
            tilt_angles=[-30.0, 0.0, 30.0],
            n_tilts=3, mtime=1234567890.0,
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_empty",
            mdoc_path=str(mdoc_empty),
            tilt_angles=None,
            n_tilts=None,
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_nopath",
            tilt_angles=[-10.0, 0.0, 10.0],
        ))
        # Soft-deleted parent
        s.add(orm.SampleORM(
            sample_id="sample_dead", data_source=DataSource.experimental, project=Project.chromatin,
            deleted_at=time.time(),
        ))
        s.add(orm.AcquisitionORM(sample_id="sample_dead", acquisition_id="acq1"))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_dead", acquisition_id="acq1", tilt_series_id="ts_zarr",
            mdoc_path=str(mdoc_zarr), zarr_path=str(zarr_path),
            tilt_angles=[0.0],
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


# ── preview.png ─────────────────────────────────────────────────────────

def test_preview_zarr_returns_png(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_zarr/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_frames_fallback_returns_png(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_frames/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_no_viewable_images_422(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_empty/preview.png")
    assert r.status_code == 422


def test_preview_no_path_at_all_422(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_nopath/preview.png")
    assert r.status_code == 422


def test_preview_unknown_tilt_series_404(client):
    r = client.get("/tilt-series/sample_a/acq1/nope/preview.png")
    assert r.status_code == 404


def test_preview_soft_deleted_parent_404(client):
    r = client.get("/tilt-series/sample_dead/acq1/ts_zarr/preview.png")
    assert r.status_code == 404


# ── polar.png ───────────────────────────────────────────────────────────

def test_polar_returns_png(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_zarr/polar.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_polar_cache_returns_same_bytes(client):
    r1 = client.get("/tilt-series/sample_a/acq1/ts_zarr/polar.png")
    r2 = client.get("/tilt-series/sample_a/acq1/ts_zarr/polar.png")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.content == r2.content


def test_polar_missing_angles_422(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_empty/polar.png")
    assert r.status_code == 422


def test_polar_unknown_tilt_series_404(client):
    r = client.get("/tilt-series/sample_a/acq1/nope/polar.png")
    assert r.status_code == 404
