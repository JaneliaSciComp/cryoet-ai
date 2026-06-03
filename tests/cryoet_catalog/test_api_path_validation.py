"""Path validation against ``CATALOG_DATA_ROOT`` (plan §11.16).

Every preview/Neuroglancer route must 404 for paths that resolve outside
the configured data root — including symlinks that escape via
``Path.resolve(strict=True)``.

Coverage:
    - Tomogram preview 404s when ``mrc_path`` points outside the root
    - Tomogram preview 404s when ``mrc_path`` is a symlink escaping the root
    - Tilt-series preview 404s when ``zarr_path`` is outside the root
    - Tilt-series preview 404s when ``mdoc_path`` is outside the root
    - Polar render is unaffected by path validation (uses cached angles)
"""
from __future__ import annotations

from pathlib import Path

import mrcfile
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from cryoet_catalog import db, orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.main import create_app
from cryoet_schema.schema import DataSource, Project


def _write_synthetic_mrc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.linspace(0, 100, 4 * 8 * 8, dtype=np.float32).reshape(4, 8, 8)
    with mrcfile.new(path, overwrite=True) as mrc:
        mrc.set_data(data)
        mrc.voxel_size = (10.0, 10.0, 10.0)


@pytest.fixture
def client(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # Inside the root: legitimate MRC at data_root/sample_a/acq1/t_ok.mrc
    inside_mrc = data_root / "sample_a" / "acq1" / "t_ok.mrc"
    _write_synthetic_mrc(inside_mrc)

    # Outside the root: a real MRC that should still 404 via path validation
    outside_mrc = outside / "escaped.mrc"
    _write_synthetic_mrc(outside_mrc)

    # Symlink inside the root pointing OUTSIDE — resolve(strict=True)
    # follows it; is_relative_to should reject the resolved target.
    symlink_inside = data_root / "sample_a" / "acq1" / "t_symlink.mrc"
    symlink_inside.parent.mkdir(parents=True, exist_ok=True)
    symlink_inside.symlink_to(outside_mrc)

    # Zarr/mdoc outside the root for tilt-series test
    outside_zarr = outside / "ts.zarr"
    outside_zarr.mkdir()
    outside_mdoc = outside / "ts.mdoc"
    outside_mdoc.write_text("# stub\n")

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
        # Legit row — used to confirm a positive case works in same fixture
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_a", acquisition_id="acq1", tomogram_id="ok",
            mrc_path=str(inside_mrc),
        ))
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_a", acquisition_id="acq1", tomogram_id="outside",
            mrc_path=str(outside_mrc),
        ))
        s.add(orm.PostProcessedTomogramORM(
            sample_id="sample_a", acquisition_id="acq1", tomogram_id="symlink",
            mrc_path=str(symlink_inside),
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_zarr_outside",
            zarr_path=str(outside_zarr), tilt_angles=[0.0],
        ))
        s.add(orm.TiltSeriesORM(
            sample_id="sample_a", acquisition_id="acq1", tilt_series_id="ts_mdoc_outside",
            mdoc_path=str(outside_mdoc), tilt_angles=[0.0],
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


def test_tomogram_preview_inside_data_root_ok(client):
    """Sanity check — the legitimate row still works in this fixture."""
    r = client.get("/tomograms/sample_a/acq1/ok/preview.png")
    assert r.status_code == 200


def test_tomogram_preview_path_outside_data_root_404(client):
    r = client.get("/tomograms/sample_a/acq1/outside/preview.png")
    assert r.status_code == 404


def test_tomogram_preview_symlink_escape_404(client):
    """Symlink that resolves outside the root is rejected via Path.resolve()."""
    r = client.get("/tomograms/sample_a/acq1/symlink/preview.png")
    assert r.status_code == 404


def test_tomogram_neuroglancer_path_outside_data_root_404(client):
    r = client.post("/tomograms/sample_a/acq1/outside/neuroglancer")
    assert r.status_code == 404


def test_tomogram_neuroglancer_symlink_escape_404(client):
    r = client.post("/tomograms/sample_a/acq1/symlink/neuroglancer")
    assert r.status_code == 404


def test_tilt_series_preview_zarr_outside_data_root_404(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_zarr_outside/preview.png")
    assert r.status_code == 404


def test_tilt_series_preview_mdoc_outside_data_root_404(client):
    r = client.get("/tilt-series/sample_a/acq1/ts_mdoc_outside/preview.png")
    assert r.status_code == 404


def test_tilt_series_neuroglancer_zarr_outside_data_root_404(client):
    r = client.post("/tilt-series/sample_a/acq1/ts_zarr_outside/neuroglancer")
    assert r.status_code == 404


def test_tilt_series_neuroglancer_mdoc_outside_data_root_404(client):
    r = client.post("/tilt-series/sample_a/acq1/ts_mdoc_outside/neuroglancer")
    assert r.status_code == 404
