"""Tests for catalog.persistence.upsert_sample_record."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    Chromatin,
    Fiducial,
    Label,
    MdRun,
    MdSource,
    PostProcessedTomogram,
    RawTomogram,
    Sample,
    SampleRecord,
    Simulation,
)
from schema.loader import ExtrasEntry
from schema.schema import DataSource, Project

from catalog import db, orm
from catalog.assembler import ScanWarning
from catalog.persistence import upsert_sample_record


@pytest.fixture
def session():
    engine = db.make_engine("sqlite:///:memory:")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _make_record(sample_id: str = "s1", **overrides) -> SampleRecord:
    sample = Sample(
        sample_id=sample_id,
        data_source=DataSource.experimental,
        project=Project.chromatin,
    )
    return SampleRecord(sample=sample, **overrides)


def test_upsert_basic_sample(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.sample_id == "s1"
    assert row.deleted_at is None


def test_upsert_resurrects_soft_deleted(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    # Force a soft delete.
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()
    assert session.get(orm.SampleORM, "s1").deleted_at is not None

    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.SampleORM, "s1").deleted_at is None


def test_upsert_chromatin_then_remove(session):
    r1 = _make_record(chromatin=Chromatin(buffer="HEPES"))
    upsert_sample_record(
        session, r1, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    chrom = session.get(orm.ChromatinORM, "s1")
    assert chrom is not None
    assert chrom.buffer == "HEPES"

    # Re-upsert with no chromatin block — row must be deleted.
    r2 = _make_record()
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.ChromatinORM, "s1") is None


def test_upsert_fiducial_then_remove(session):
    r1 = _make_record(
        fiducial=Fiducial(vendor="Aurion", aunp_size_nm=10.0)
    )
    upsert_sample_record(
        session, r1, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    fid = session.get(orm.FiducialORM, "s1")
    assert fid is not None
    assert fid.vendor == "Aurion"
    assert fid.aunp_size_nm == 10.0

    r2 = _make_record()
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.FiducialORM, "s1") is None


def test_upsert_label_ordinal_cleanup(session):
    r1 = _make_record(
        label=[
            Label(label_target="actin", aunp_size_nm=5.0),
            Label(label_target="tubulin", aunp_size_nm=10.0),
            Label(label_target="myosin", aunp_size_nm=15.0),
        ]
    )
    upsert_sample_record(
        session, r1, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == "s1")
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert [a.ordinal for a in rows] == [0, 1, 2]
    assert [a.label_target for a in rows] == ["actin", "tubulin", "myosin"]
    assert [a.aunp_size_nm for a in rows] == [5.0, 10.0, 15.0]

    # Reduce to two — ordinal 2 must be cleaned up.
    r2 = _make_record(
        label=[
            Label(label_target="actin", aunp_size_nm=5.0),
            Label(label_target="tubulin", aunp_size_nm=10.0),
        ]
    )
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == "s1")
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert [a.ordinal for a in rows] == [0, 1]


def test_label_aunp_size_nm_polymorphic(session):
    """``Label.aunp_size_nm`` is ``float | list[float] | None`` — both round-trip."""
    r = _make_record(
        label=[
            Label(label_target="x", aunp_size_nm=5.0),
            Label(label_target="y", aunp_size_nm=[5.0, 10.0]),
            Label(label_target="z", aunp_size_nm=None),
        ]
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.LabelORM)
            .where(orm.LabelORM.sample_id == "s1")
            .order_by(orm.LabelORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert rows[0].aunp_size_nm == 5.0
    assert rows[1].aunp_size_nm == [5.0, 10.0]
    assert rows[2].aunp_size_nm is None


def test_upsert_raw_and_post_tomogram_share_id_namespace(session):
    """One acquisition can carry a raw tomogram + one or more post-processed
    tomograms; both land in their respective tables under the same composite PK
    shape (sample_id, acquisition_id, tomogram_id).
    """
    raw = RawTomogram(id="t_raw", voxel_size=11.72)
    post1 = PostProcessedTomogram(
        id="t_post1", voxel_size=11.72, size_bytes=12345
    )
    post2 = PostProcessedTomogram(
        id="t_post2", voxel_size=11.72, denoising_software="cryoCARE"
    )
    ann = Annotation(id="a1", target_tomogram="t_post1", files=["x.mrc"])
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        raw_tomogram=raw,
        post_processed_tomogram=[post1, post2],
        annotation=[ann],
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()

    raw_row = session.get(orm.RawTomogramORM, ("s1", "acq1", "t_raw"))
    assert raw_row is not None
    assert raw_row.voxel_size == pytest.approx(11.72)

    post1_row = session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t_post1")
    )
    assert post1_row is not None
    assert post1_row.size_bytes == 12345

    post2_row = session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t_post2")
    )
    assert post2_row is not None
    assert post2_row.denoising_software == "cryoCARE"

    ann_row = session.get(orm.AnnotationORM, ("s1", "acq1", "a1"))
    assert ann_row is not None
    assert ann_row.files == ["x.mrc"]
    assert ann_row.target_tomogram == "t_post1"


def test_stale_raw_tomogram_cleaned_up_on_disappearance(session):
    raw = RawTomogram(id="t_raw")
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        raw_tomogram=raw,
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    assert session.get(orm.RawTomogramORM, ("s1", "acq1", "t_raw")) is not None

    # Drop the raw tomogram in the next upsert.
    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.RawTomogramORM, ("s1", "acq1", "t_raw")) is None


def test_stale_post_processed_tomogram_cleaned_up(session):
    tomos1 = [
        PostProcessedTomogram(id="t1"),
        PostProcessedTomogram(id="t2"),
    ]
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos1,
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t2")
    ) is not None

    tomos2 = [PostProcessedTomogram(id="t1")]
    acq_file2 = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos2,
    )
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t1")
    ) is not None
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t2")
    ) is None


def test_md_run_and_md_source_round_trip(session):
    """Simulation samples carry [[md_run]] at sample scope and ``[md_source]``
    per acquisition; both upsert and clear on disappearance."""
    sample = Sample(
        sample_id="sim1",
        data_source=DataSource.simulation,
        project=Project.chromatin,
    )
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        md_source=MdSource(md_run_id="run_a", frame=42),
    )
    r = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type="test"),
        md_run=[MdRun(id="run_a", seed=123, computer="dgx-01")],
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()

    md_run_row = session.get(orm.MdRunORM, ("sim1", "run_a"))
    assert md_run_row is not None
    assert md_run_row.seed == 123
    assert md_run_row.computer == "dgx-01"

    md_source_row = session.get(orm.MdSourceORM, ("sim1", "acq1"))
    assert md_source_row is not None
    assert md_source_row.md_run_id == "run_a"
    assert md_source_row.frame == 42

    # Re-upsert without md_source — row must be deleted while md_run stays.
    acq_file2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    r2 = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type="test"),
        md_run=r.md_run,
        acquisitions={"acq1": acq_file2},
    )
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.MdSourceORM, ("sim1", "acq1")) is None
    assert session.get(orm.MdRunORM, ("sim1", "run_a")) is not None

    # Now drop md_run too.
    r3 = SampleRecord(
        sample=sample,
        simulation=Simulation(dataset_type="test"),
        acquisitions={"acq1": acq_file2},
    )
    upsert_sample_record(
        session, r3, extras=[], warnings=[], scan_run_id="run-3"
    )
    session.commit()
    assert session.get(orm.MdRunORM, ("sim1", "run_a")) is None


def test_stale_acquisition_cleaned_up(session):
    acq1 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    acq2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq2"))
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq1, "acq2": acq2},
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    assert session.get(orm.AcquisitionORM, ("s1", "acq2")) is not None

    # Re-upsert without acq2.
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq1})
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.AcquisitionORM, ("s1", "acq1")) is not None
    assert session.get(orm.AcquisitionORM, ("s1", "acq2")) is None


def test_extras_refresh(session):
    r = _make_record()
    extras = [
        ExtrasEntry(
            entity_type="sample",
            entity_pk=("s1",),
            key="weird_key",
            value="weird_value",
        ),
        ExtrasEntry(
            entity_type="label",
            entity_pk=("s1", 0),
            key="custom",
            value={"nested": 1},
        ),
    ]
    upsert_sample_record(
        session, r, extras=extras, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == "s1")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2

    # Re-upsert with one fewer extra — old ones must be gone.
    upsert_sample_record(
        session, r, extras=extras[:1], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == "s1")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert json.loads(rows[0].entity_pk_json) == ["s1"]
    assert json.loads(rows[0].value_json) == "weird_value"


def test_extras_value_json_handles_dates(session):
    """json.dumps default fallback handles datetime.date for safety."""
    import datetime

    r = _make_record()
    extras = [
        ExtrasEntry(
            entity_type="milling",
            entity_pk=("s1",),
            key="custom_date",
            value=datetime.date(2026, 5, 1),
        )
    ]
    upsert_sample_record(
        session, r, extras=extras, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    row = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == "s1")
        )
        .scalars()
        .one()
    )
    assert json.loads(row.value_json) == "2026-05-01"


def test_warnings_refresh_with_scan_run_id(session):
    r = _make_record()
    ws = [ScanWarning(category="extra_field", location="sample", message="x")]
    upsert_sample_record(
        session, r, extras=[], warnings=ws, scan_run_id="run-1"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ScanWarningsORM).where(
                orm.ScanWarningsORM.sample_id == "s1"
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].scan_run_id == "run-1"
    assert rows[0].category == "extra_field"
    assert rows[0].detected_at > 0

    # Re-upsert with no warnings — old ones must be gone.
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.ScanWarningsORM).where(
                orm.ScanWarningsORM.sample_id == "s1"
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0


def test_idempotent_double_upsert_same_state(session):
    r = _make_record(
        chromatin=Chromatin(buffer="HEPES"),
        label=[Label(label_target="actin", aunp_size_nm=5.0)],
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()
    samples = session.execute(select(orm.SampleORM)).scalars().all()
    chromatin = session.execute(select(orm.ChromatinORM)).scalars().all()
    labels = session.execute(select(orm.LabelORM)).scalars().all()
    assert len(samples) == 1
    assert len(chromatin) == 1
    assert len(labels) == 1


def test_unflushed_inserts_dont_get_deleted_by_stale_cleanup(session):
    """Adding a new tomogram in a follow-up upsert must not be wiped by the
    stale-row cleanup. Regression guard for the keep-set logic."""
    tomos1 = [PostProcessedTomogram(id="t1")]
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos1,
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.experimental,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()

    tomos2 = [
        PostProcessedTomogram(id="t1"),
        PostProcessedTomogram(id="t2"),
    ]
    acq_file2 = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        post_processed_tomogram=tomos2,
    )
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], warnings=[], scan_run_id="run-2"
    )
    session.commit()

    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t1")
    ) is not None
    assert session.get(
        orm.PostProcessedTomogramORM, ("s1", "acq1", "t2")
    ) is not None


def test_upsert_writes_disk_size_bytes(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1", disk_size_bytes=12345
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.disk_size_bytes == 12345


def test_upsert_default_disk_size_bytes_is_null(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.disk_size_bytes is None


def test_upsert_sample_record_with_thumbnail_path(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1",
        thumbnail_path="s/a/t.png",
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.thumbnail_path == "s/a/t.png"


def test_upsert_sample_record_thumbnail_path_default_is_null(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], warnings=[], scan_run_id="run-1"
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.thumbnail_path is None


def test_per_sample_isolation_scan_warnings_only_for_target_sample(session):
    """Warnings refresh deletes only this sample's rows, not all."""
    r1 = _make_record(sample_id="s1")
    r2 = _make_record(sample_id="s2")
    w1 = [ScanWarning(category="extra_field", location="sample", message="m1")]
    w2 = [ScanWarning(category="extra_field", location="sample", message="m2")]
    upsert_sample_record(
        session, r1, extras=[], warnings=w1, scan_run_id="r"
    )
    upsert_sample_record(
        session, r2, extras=[], warnings=w2, scan_run_id="r"
    )
    session.commit()
    # Re-upsert s1 without warnings — s2's warning must remain.
    upsert_sample_record(
        session, r1, extras=[], warnings=[], scan_run_id="r"
    )
    session.commit()
    s1_rows = (
        session.execute(
            select(orm.ScanWarningsORM).where(
                orm.ScanWarningsORM.sample_id == "s1"
            )
        )
        .scalars()
        .all()
    )
    s2_rows = (
        session.execute(
            select(orm.ScanWarningsORM).where(
                orm.ScanWarningsORM.sample_id == "s2"
            )
        )
        .scalars()
        .all()
    )
    assert len(s1_rows) == 0
    assert len(s2_rows) == 1
