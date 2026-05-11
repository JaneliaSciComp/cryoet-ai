"""Tilt-series upsert + soft-delete behavior.

Per plan decision §11.22, ``tilt_series`` rows are **left untouched** on
soft-delete (same convention as every other child table). Resurrection via
re-upsert re-populates the rows.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cryoet_schema import (
    Acquisition,
    AcquisitionFile,
    Sample,
    SampleRecord,
    TiltSeries,
)
from cryoet_schema.schema import DataSource, Project

from cryoet_catalog import db, orm
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


def _make_record_with_tilt_series(
    sample_id: str = "s1", *, tilt_series_ids: tuple[str, ...] = ("ts_a",)
) -> SampleRecord:
    acq = Acquisition(acquisition_id="Pos1")
    ts_list = [
        TiltSeries(
            tilt_series_id=tid,
            mdoc_path=f"/data/{sample_id}/Pos1/Frames/{tid}.mdoc",
            n_tilts=41,
            tilt_range_min=-60.0,
            tilt_range_max=60.0,
            image_format="EER",
            tilt_angles=[-60.0, -57.0, -54.0],
            mtime=1234567890.0,
        )
        for tid in tilt_series_ids
    ]
    return SampleRecord(
        sample=Sample(
            sample_id=sample_id,
            data_source=DataSource.cryoet,
            project=Project.chromatin,
        ),
        acquisitions={
            "Pos1": AcquisitionFile(
                acquisition=acq, tomogram=[], annotation=[], tilt_series=ts_list
            )
        },
    )


def test_upsert_writes_tilt_series_row(session) -> None:
    r = _make_record_with_tilt_series()
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.sample_id == "s1"
    assert row.acquisition_id == "Pos1"
    assert row.tilt_series_id == "ts_a"
    assert row.n_tilts == 41
    assert row.image_format == "EER"
    assert row.tilt_angles == [-60.0, -57.0, -54.0]


def test_soft_delete_leaves_tilt_series_rows_in_place(session) -> None:
    r = _make_record_with_tilt_series()
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    # Mimic ``soft_delete_missing_samples``: only flip ``deleted_at``,
    # never touch child rows.
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert len(rows) == 1, (
        "tilt_series rows must survive soft-delete — same convention as "
        "tomograms/annotations (plan §11.22)"
    )


def test_resurrection_via_reupsert_brings_tilt_series_back(session) -> None:
    r = _make_record_with_tilt_series()
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.execute(
        orm.SampleORM.__table__.update().values(deleted_at=time.time())
    )
    session.commit()

    # Re-upsert (resurrection path) clears deleted_at and the surviving
    # tilt_series rows remain reachable.
    upsert_sample_record(
        session, r, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()

    sample = session.get(orm.SampleORM, "s1")
    assert sample is not None
    assert sample.deleted_at is None
    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert {(r.tilt_series_id,) for r in rows} == {("ts_a",)}


def test_upsert_removes_stale_tilt_series_rows(session) -> None:
    """Re-upserting with a smaller tilt_series set deletes the dropped row."""
    r1 = _make_record_with_tilt_series(tilt_series_ids=("ts_a", "ts_b"))
    upsert_sample_record(
        session, r1, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-1"
    )
    session.commit()
    assert (
        len(session.execute(select(orm.TiltSeriesORM)).scalars().all()) == 2
    )

    r2 = _make_record_with_tilt_series(tilt_series_ids=("ts_a",))
    upsert_sample_record(
        session, r2, extras=[], tomogram_aux={}, warnings=[], scan_run_id="run-2"
    )
    session.commit()

    rows = session.execute(select(orm.TiltSeriesORM)).scalars().all()
    assert [r.tilt_series_id for r in rows] == ["ts_a"]
