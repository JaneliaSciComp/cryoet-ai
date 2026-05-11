"""``[[tilt_series]]`` TOML extras round-trip through the extras table.

Plan decision §11.24: researchers can attach custom metadata to a
``[[tilt_series]]`` block; unknown keys flow through ``cryoet_schema.loader``'s
extras walker as ``entity_type='tilt_series'`` entries, get persisted by
``upsert_sample_record``, and survive a round-trip read.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

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
from cryoet_schema.loader import (
    ExtrasEntry,
    _format_extras_location,
    _walk_extras,
    load_sample_record,
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


def _build_record_with_tilt_series_extras() -> SampleRecord:
    """Build a record where a TiltSeries has an unknown TOML key.

    ``model_extra`` on a pydantic model is populated by passing unknown
    kwargs through ``model_construct``. We do the same here so the walker
    treats it as a TOML-authored extra.
    """
    ts = TiltSeries.model_validate(
        {
            "tilt_series_id": "ts_a",
            "n_tilts": 41,
            # arbitrary extra key, like a researcher added 'custom_qc'
            "custom_qc": {"score": 0.92, "reviewer": "ksmith"},
        }
    )
    return SampleRecord(
        sample=Sample(
            sample_id="s1",
            data_source=DataSource.cryoet,
            project=Project.chromatin,
        ),
        acquisitions={
            "Pos1": AcquisitionFile(
                acquisition=Acquisition(acquisition_id="Pos1"),
                tomogram=[],
                annotation=[],
                tilt_series=[ts],
            )
        },
    )


def test_walk_extras_emits_tilt_series_entry() -> None:
    record = _build_record_with_tilt_series_extras()
    entries = _walk_extras(record)
    ts_entries = [e for e in entries if e.entity_type == "tilt_series"]
    assert len(ts_entries) == 1
    entry = ts_entries[0]
    assert entry.entity_pk == ("s1", "Pos1", "ts_a")
    assert entry.key == "custom_qc"
    assert entry.value == {"score": 0.92, "reviewer": "ksmith"}


def test_format_extras_location_for_tilt_series() -> None:
    entry = ExtrasEntry(
        entity_type="tilt_series",
        entity_pk=("s1", "Pos1", "ts_a"),
        key="custom_qc",
        value=None,
    )
    assert _format_extras_location(entry) == "acquisitions.Pos1.tilt_series[ts_a]"


def test_upsert_persists_tilt_series_extras(session) -> None:
    record = _build_record_with_tilt_series_extras()
    extras = _walk_extras(record)
    upsert_sample_record(
        session,
        record,
        extras=extras,
        tomogram_aux={},
        warnings=[],
        scan_run_id="run-1",
    )
    session.commit()

    rows = (
        session.execute(
            select(orm.ExtrasORM).where(orm.ExtrasORM.entity_type == "tilt_series")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_type == "tilt_series"
    assert json.loads(row.entity_pk_json) == ["s1", "Pos1", "ts_a"]
    assert row.key == "custom_qc"
    assert json.loads(row.value_json) == {"score": 0.92, "reviewer": "ksmith"}


def test_load_sample_record_emits_tilt_series_extras(tmp_path: Path) -> None:
    """End-to-end through ``load_sample_record``: TOML with ``[[tilt_series]]``
    + unknown key produces a tilt_series extras entry."""
    sample_dir = tmp_path / "s1"
    (sample_dir).mkdir()
    (sample_dir / "sample.toml").write_text(
        textwrap.dedent(
            """\
            [sample]
            data_source = "cryoet"
            project = "chromatin"
            """
        )
    )
    pos1 = sample_dir / "Pos1"
    pos1.mkdir()
    (pos1 / "acquisition.toml").write_text(
        textwrap.dedent(
            """\
            [acquisition]
            microscope = "Krios"

            [[tilt_series]]
            tilt_series_id = "ts_a"
            n_tilts = 41
            custom_qc = "passed"
            """
        )
    )

    result = load_sample_record(sample_dir)
    assert result.record is not None
    ts_extras = [e for e in result.extras if e.entity_type == "tilt_series"]
    assert len(ts_extras) == 1
    assert ts_extras[0].key == "custom_qc"
    assert ts_extras[0].entity_pk == ("s1", "Pos1", "ts_a")
