import time
import pytest
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from cryoet_schema import SampleRecord, Sample, Chromatin, Aunp, Acquisition, Tomogram, Annotation, AcquisitionFile
from cryoet_schema.schema import DataSource, Project
from cryoet_schema.loader import ExtrasEntry
from cryoet_catalog import db, orm
from cryoet_catalog.assembler import ScanWarning
from cryoet_catalog.persistence import upsert_sample_record
from cryoet_catalog.api.main import create_app
from cryoet_catalog.api.deps import get_session


@pytest.fixture
def client(tmp_path):
    # Use a temp-file SQLite (not :memory:) so multiple connections share state.
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    # Bypass lifespan engine setup — store directly
    app.state.engine = engine

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    # Seed
    s = Session()
    try:
        # sample_a — full with everything
        tomo = Tomogram(id="t1", voxel_bin=4)
        ann = Annotation(id="a1", target_tomogram="t1", files=["x.mrc"])
        acq = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"), tomogram=[tomo], annotation=[ann])
        rec_a = SampleRecord(
            sample=Sample(sample_id="sample_a", data_source=DataSource.cryoet, project=Project.chromatin, description="A"),
            chromatin=Chromatin(buffer="HEPES"),
            aunp=[Aunp(size_nm=5.0)],
            acquisitions={"acq1": acq},
        )
        upsert_sample_record(s, rec_a, extras=[
            ExtrasEntry(entity_type="sample", entity_pk=("sample_a",), key="weird", value="value"),
            ExtrasEntry(entity_type="chromatin", entity_pk=("sample_a",), key="weird", value=1),
        ], tomogram_aux={
            ("sample_a", "acq1", "t1"): {"voxel_spacing_angstrom": 11.72, "voxel_spacing_angstrom_implied": 11.72},
        }, warnings=[
            ScanWarning(category="extra_field", location="sample", message="extra field 'weird'"),
        ], scan_run_id="run-A")

        # sample_b — minimal
        rec_b = SampleRecord(sample=Sample(sample_id="sample_b", data_source=DataSource.simulation, project=Project.synapse))
        upsert_sample_record(s, rec_b, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-A")

        # sample_c — soft-deleted (filter test)
        rec_c = SampleRecord(sample=Sample(sample_id="sample_c", data_source=DataSource.cryoet, project=Project.chromatin))
        upsert_sample_record(s, rec_c, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-A")
        from sqlalchemy import update as sa_update
        s.execute(sa_update(orm.SampleORM).where(orm.SampleORM.sample_id == "sample_c").values(deleted_at=time.time()))

        # scans rows
        s.add(orm.ScansORM(
            scan_run_id="run-A", started_at=time.time()-100, ended_at=time.time()-50,
            root="/data", status="completed",
            samples_upserted=2, samples_skipped=0, samples_failed=0,
        ))
        s.add(orm.ScansORM(
            scan_run_id="run-B", started_at=time.time()-10, ended_at=None,
            root="/data", status="running",
            samples_upserted=None, samples_skipped=None, samples_failed=None,
        ))
        s.commit()
    finally:
        s.close()

    return TestClient(app)


# ── /samples ──────────────────────────────────────────────
def test_list_samples_excludes_soft_deleted(client):
    r = client.get("/samples")
    assert r.status_code == 200
    ids = {s["sample_id"] for s in r.json()}
    assert ids == {"sample_a", "sample_b"}
    assert "sample_c" not in ids


def test_list_samples_filter_project(client):
    r = client.get("/samples", params={"project": "chromatin"})
    assert r.status_code == 200
    assert {s["sample_id"] for s in r.json()} == {"sample_a"}


def test_list_samples_filter_data_source(client):
    r = client.get("/samples", params={"data_source": "simulation"})
    assert {s["sample_id"] for s in r.json()} == {"sample_b"}


def test_list_samples_filter_has_warnings(client):
    r = client.get("/samples", params={"has_warnings": "true"})
    ids = {s["sample_id"] for s in r.json()}
    assert "sample_a" in ids   # has 1 warning
    assert "sample_b" not in ids

    r = client.get("/samples", params={"has_warnings": "false"})
    ids = {s["sample_id"] for s in r.json()}
    assert "sample_b" in ids
    assert "sample_a" not in ids


def test_list_samples_includes_warning_count(client):
    r = client.get("/samples")
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_a"]["warning_count"] == 1
    assert by_id["sample_b"]["warning_count"] == 0


def test_list_samples_includes_child_counts(client):
    """sample_a is seeded with 1 acquisition, 1 tomogram, 0 tilt_series."""
    r = client.get("/samples")
    by_id = {s["sample_id"]: s for s in r.json()}
    assert by_id["sample_a"]["n_acquisitions"] == 1
    assert by_id["sample_a"]["n_tomograms"] == 1
    assert by_id["sample_a"]["n_tilt_series"] == 0
    assert by_id["sample_b"]["n_acquisitions"] == 0
    assert by_id["sample_b"]["n_tomograms"] == 0
    assert by_id["sample_b"]["n_tilt_series"] == 0


def test_list_samples_pagination(client):
    r = client.get("/samples", params={"limit": 1, "offset": 0})
    assert len(r.json()) == 1
    r2 = client.get("/samples", params={"limit": 1, "offset": 1})
    assert len(r2.json()) == 1
    assert r.json()[0]["sample_id"] != r2.json()[0]["sample_id"]


# ── /samples/{id} ─────────────────────────────────────────
def test_get_sample_detail(client):
    r = client.get("/samples/sample_a")
    assert r.status_code == 200
    body = r.json()
    assert body["sample_id"] == "sample_a"
    assert body["chromatin"] is not None
    assert body["chromatin"]["buffer"] == "HEPES"
    assert body["aunp"][0]["size_nm"] == 5.0
    assert len(body["acquisitions"]) == 1
    acq = body["acquisitions"][0]
    assert acq["acquisition_id"] == "acq1"
    assert acq["tomograms"][0]["voxel_spacing_angstrom"] == pytest.approx(11.72)


def test_get_sample_404(client):
    r = client.get("/samples/missing")
    assert r.status_code == 404


def test_get_sample_soft_deleted_404(client):
    r = client.get("/samples/sample_c")
    assert r.status_code == 404


# ── /samples/{id}/warnings ────────────────────────────────
def test_warnings_for_sample(client):
    r = client.get("/samples/sample_a/warnings")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["category"] == "extra_field"
    assert body[0]["scan_run_id"] == "run-A"


def test_warnings_for_soft_deleted_404(client):
    r = client.get("/samples/sample_c/warnings")
    assert r.status_code == 404


# ── /scans ────────────────────────────────────────────────
def test_list_scans_descending_by_start(client):
    r = client.get("/scans")
    assert r.status_code == 200
    ids = [s["scan_run_id"] for s in r.json()]
    # run-B started later
    assert ids == ["run-B", "run-A"]


def test_get_latest_completed(client):
    r = client.get("/scans/latest")
    assert r.status_code == 200
    assert r.json()["scan_run_id"] == "run-A"


# ── /extras/summary ───────────────────────────────────────
def test_extras_summary(client):
    r = client.get("/extras/summary")
    assert r.status_code == 200
    body = r.json()
    # Two rows: sample/weird × 1, chromatin/weird × 1
    assert {(row["entity_type"], row["key"], row["count"]) for row in body} == {
        ("sample", "weird", 1), ("chromatin", "weird", 1),
    }
