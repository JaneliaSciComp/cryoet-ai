"""Tests for cryoet_catalog.persistence.upsert_sample_record."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cryoet_schema import (
    Acquisition,
    AcquisitionFile,
    Annotation,
    Aunp,
    Chromatin,
    Sample,
    SampleRecord,
    Tomogram,
)
from cryoet_schema.loader import ExtrasEntry
from cryoet_schema.schema import DataSource, Project

from cryoet_catalog import db, orm
from cryoet_catalog.assembler import ScanWarning
from cryoet_catalog.persistence import upsert_sample_record


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
        data_source=DataSource.cryoet,
        project=Project.chromatin,
    )
    return SampleRecord(sample=sample, **overrides)


def test_upsert_basic_sample(session):
    r = _make_record()
    upsert_sample_record(
        session,
        r,
        extras=[],
        tomogram_aux={},
        warnings=[],
        scan_run_id="run-1",
    )
    session.commit()
    row = session.get(orm.SampleORM, "s1")
    assert row is not None
    assert row.sample_id == "s1"
    assert row.deleted_at is None


def test_upsert_resurrects_soft_deleted(session):
    r = _make_record()
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    # Force a soft delete.
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()
    assert session.get(orm.SampleORM, "s1").deleted_at is not None

    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.SampleORM, "s1").deleted_at is None


def test_upsert_chromatin_then_remove(session):
    r1 = _make_record(chromatin=Chromatin(buffer="HEPES"))
    upsert_sample_record(
        session, r1, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    chrom = session.get(orm.ChromatinORM, "s1")
    assert chrom is not None
    assert chrom.buffer == "HEPES"

    # Re-upsert with no chromatin block — row must be deleted.
    r2 = _make_record()
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.ChromatinORM, "s1") is None


def test_upsert_aunp_ordinal_cleanup(session):
    r1 = _make_record(
        aunp=[
            Aunp(size_nm=5.0),
            Aunp(size_nm=10.0),
            Aunp(size_nm=15.0),
        ]
    )
    upsert_sample_record(
        session, r1, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.AunpORM)
            .where(orm.AunpORM.sample_id == "s1")
            .order_by(orm.AunpORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert [a.ordinal for a in rows] == [0, 1, 2]
    assert [a.size_nm for a in rows] == [5.0, 10.0, 15.0]

    # Reduce to two — ordinal 2 must be cleaned up.
    r2 = _make_record(aunp=[Aunp(size_nm=5.0), Aunp(size_nm=10.0)])
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()
    rows = (
        session.execute(
            select(orm.AunpORM)
            .where(orm.AunpORM.sample_id == "s1")
            .order_by(orm.AunpORM.ordinal)
        )
        .scalars()
        .all()
    )
    assert [a.ordinal for a in rows] == [0, 1]


def test_upsert_acquisition_with_tomogram_and_annotation(session):
    tomo = Tomogram(id="t1", voxel_bin=4)
    ann = Annotation(id="a1", target_tomogram="t1", files=["x.mrc"])
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"),
        tomogram=[tomo],
        annotation=[ann],
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.cryoet,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    aux = {
        ("s1", "acq1", "t1"): {
            "voxel_spacing_angstrom": 11.72,
            "voxel_spacing_angstrom_implied": 11.72,
        }
    }
    upsert_sample_record(
        session,
        r,
        extras=[],
        tomogram_aux=aux,
        warnings=[],
        scan_run_id="run-1",
    )
    session.commit()

    acq_row = session.get(orm.AcquisitionORM, ("s1", "acq1"))
    assert acq_row is not None

    tomo_row = session.get(orm.TomogramORM, ("s1", "acq1", "t1"))
    assert tomo_row is not None
    assert tomo_row.voxel_bin == 4
    assert tomo_row.voxel_spacing_angstrom == pytest.approx(11.72)
    assert tomo_row.voxel_spacing_angstrom_implied == pytest.approx(11.72)

    ann_row = session.get(orm.AnnotationORM, ("s1", "acq1", "a1"))
    assert ann_row is not None
    assert ann_row.files == ["x.mrc"]
    assert ann_row.target_tomogram == "t1"


def test_stale_tomogram_cleaned_up(session):
    tomos1 = [Tomogram(id="t1"), Tomogram(id="t2")]
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), tomogram=tomos1
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.cryoet,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    assert session.get(orm.TomogramORM, ("s1", "acq1", "t2")) is not None

    # Drop t2.
    tomos2 = [Tomogram(id="t1")]
    acq_file2 = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), tomogram=tomos2
    )
    r2 = SampleRecord(
        sample=r.sample, acquisitions={"acq1": acq_file2}
    )
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()
    assert session.get(orm.TomogramORM, ("s1", "acq1", "t1")) is not None
    assert session.get(orm.TomogramORM, ("s1", "acq1", "t2")) is None


def test_stale_acquisition_cleaned_up(session):
    acq1 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq1"))
    acq2 = AcquisitionFile(acquisition=Acquisition(acquisition_id="acq2"))
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.cryoet,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq1, "acq2": acq2},
    )
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    assert session.get(orm.AcquisitionORM, ("s1", "acq2")) is not None

    # Re-upsert without acq2.
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq1})
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
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
            entity_type="aunp",
            entity_pk=("s1", 0),
            key="custom",
            value={"nested": 1},
        ),
    ]
    upsert_sample_record(
        session, r, extras=extras, tomogram_aux={}, warnings=[], scan_run_id="run-1"
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
        session,
        r,
        extras=extras[:1],
        tomogram_aux={},
        warnings=[],
        scan_run_id="run-2",
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
        session, r, extras=extras, tomogram_aux={}, warnings=[], scan_run_id="run-1"
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
        session, r, extras=[], tomogram_aux={}, warnings=ws, scan_run_id="run-1"
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
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
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
        chromatin=Chromatin(buffer="HEPES"), aunp=[Aunp(size_nm=5.0)]
    )
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()
    samples = session.execute(select(orm.SampleORM)).scalars().all()
    chromatin = session.execute(select(orm.ChromatinORM)).scalars().all()
    aunp = session.execute(select(orm.AunpORM)).scalars().all()
    assert len(samples) == 1
    assert len(chromatin) == 1
    assert len(aunp) == 1


def test_unflushed_inserts_dont_get_deleted_by_stale_cleanup(session):
    """Adding a new tomogram in a follow-up upsert must not be wiped by the
    stale-row cleanup. Regression guard for the keep-set logic."""
    tomos1 = [Tomogram(id="t1")]
    acq_file = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), tomogram=tomos1
    )
    r = SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.cryoet,
            project=Project.chromatin,
        ),
        acquisitions={"acq1": acq_file},
    )
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()

    tomos2 = [Tomogram(id="t1"), Tomogram(id="t2")]
    acq_file2 = AcquisitionFile(
        acquisition=Acquisition(acquisition_id="acq1"), tomogram=tomos2
    )
    r2 = SampleRecord(sample=r.sample, acquisitions={"acq1": acq_file2})
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()

    assert session.get(orm.TomogramORM, ("s1", "acq1", "t1")) is not None
    assert session.get(orm.TomogramORM, ("s1", "acq1", "t2")) is not None


def test_per_sample_isolation_scan_warnings_only_for_target_sample(session):
    """Warnings refresh deletes only this sample's rows, not all."""
    r1 = _make_record(sample_id="s1")
    r2 = _make_record(sample_id="s2")
    w1 = [ScanWarning(category="extra_field", location="sample", message="m1")]
    w2 = [ScanWarning(category="extra_field", location="sample", message="m2")]
    upsert_sample_record(
        session, r1, extras=[], tomogram_aux={}, warnings=w1, scan_run_id="r"
    )
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=w2, scan_run_id="r"
    )
    session.commit()
    # Re-upsert s1 without warnings — s2's warning must remain.
    upsert_sample_record(
        session, r1, extras=[], tomogram_aux={}, warnings=[], scan_run_id="r"
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
