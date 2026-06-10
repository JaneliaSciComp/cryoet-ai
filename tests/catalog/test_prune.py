"""Tests for catalog.persistence.soft_delete_missing_samples."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from schema import Sample, SampleRecord
from schema.schema import DataSource, Project

from catalog import db, orm
from catalog.persistence import (
    PruneSafetyFloorExceeded,
    soft_delete_missing_samples,
    upsert_sample_record,
)


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


def _seed(session, ids: list[str]) -> None:
    for sid in ids:
        upsert_sample_record(
            session,
            SampleRecord(
                sample=Sample(
                    sample_id=sid,
                    data_source=DataSource.experimental,
                    project=Project.chromatin,
                )
            ),
            extras=[],
            warnings=[],
            scan_run_id="seed",
        )
    session.commit()


class FakeReport:
    def __init__(self) -> None:
        self.would_soft_delete: list[str] | None = None
        self.soft_deleted: int = 0


def test_soft_delete_sets_deleted_at(session):
    _seed(session, ["a", "b", "c"])
    soft_delete_missing_samples(
        session, fs_sample_ids={"a", "b"}, safety_floor=1.0
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is None
    assert session.get(orm.SampleORM, "b").deleted_at is None
    c = session.get(orm.SampleORM, "c")
    assert c.deleted_at is not None and c.deleted_at > 0


def test_resurrection_clears_deleted_at(session):
    _seed(session, ["a"])
    soft_delete_missing_samples(
        session, fs_sample_ids=set(), safety_floor=1.0
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is not None

    # Re-upsert resurrects.
    _seed(session, ["a"])
    assert session.get(orm.SampleORM, "a").deleted_at is None


def test_safety_floor_aborts(session):
    _seed(session, ["a", "b", "c", "d"])
    # Would soft-delete 3 of 4 = 75% > default 50%.
    with pytest.raises(PruneSafetyFloorExceeded) as excinfo:
        soft_delete_missing_samples(
            session, fs_sample_ids={"a"}, safety_floor=0.5
        )
    assert excinfo.value.ratio > 0.5
    assert excinfo.value.threshold == 0.5
    assert sorted(excinfo.value.missing) == ["b", "c", "d"]
    # No samples were modified.
    rows = (
        session.execute(
            select(orm.SampleORM).where(orm.SampleORM.deleted_at.is_not(None))
        )
        .scalars()
        .all()
    )
    assert rows == []


def test_safety_floor_skipped_on_empty_db(session):
    """No live samples -> skip safety floor (first scan must not fail)."""
    soft_delete_missing_samples(
        session, fs_sample_ids=set(), safety_floor=0.5
    )


def test_dry_run_reports_without_modifying(session):
    _seed(session, ["a", "b"])
    report = FakeReport()
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a"},
        dry_run=True,
        safety_floor=1.0,
        report=report,
    )
    session.commit()
    assert report.would_soft_delete == ["b"]
    assert session.get(orm.SampleORM, "b").deleted_at is None


def test_dry_run_still_safety_floor_checks(session):
    _seed(session, ["a", "b", "c", "d"])
    with pytest.raises(PruneSafetyFloorExceeded):
        soft_delete_missing_samples(
            session,
            fs_sample_ids={"a"},
            dry_run=True,
            safety_floor=0.5,
        )


def test_already_deleted_samples_not_recounted(session):
    _seed(session, ["a", "b", "c"])
    # Pre-mark "a" as soft-deleted.
    session.execute(
        orm.SampleORM.__table__.update()
        .where(orm.SampleORM.sample_id == "a")
        .values(deleted_at=time.time())
    )
    session.commit()
    # fs has b and c — no live samples missing.
    soft_delete_missing_samples(
        session, fs_sample_ids={"b", "c"}, safety_floor=0.5
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is not None
    assert session.get(orm.SampleORM, "b").deleted_at is None
    assert session.get(orm.SampleORM, "c").deleted_at is None


def test_no_op_when_fs_matches_db(session):
    _seed(session, ["a", "b"])
    soft_delete_missing_samples(
        session, fs_sample_ids={"a", "b"}, safety_floor=0.5
    )
    session.commit()
    assert session.get(orm.SampleORM, "a").deleted_at is None
    assert session.get(orm.SampleORM, "b").deleted_at is None


def test_report_soft_deleted_counter_incremented(session):
    _seed(session, ["a", "b", "c"])
    report = FakeReport()
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a", "b"},
        safety_floor=1.0,
        report=report,
    )
    session.commit()
    assert report.soft_deleted == 1


def test_dry_run_appends_to_existing_list(session):
    """If report.would_soft_delete is already a list, extend it (not replace)."""
    _seed(session, ["a", "b"])
    report = FakeReport()
    report.would_soft_delete = ["preexisting"]
    soft_delete_missing_samples(
        session,
        fs_sample_ids={"a"},
        dry_run=True,
        safety_floor=1.0,
        report=report,
    )
    assert report.would_soft_delete == ["preexisting", "b"]
