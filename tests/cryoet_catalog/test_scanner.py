"""End-to-end scanner tests against the fixture sample tree."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cryoet_catalog import db, discovery, orm, scanner

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():
    eng = db.make_engine("sqlite:///:memory:")
    db.init_schema(eng)
    return eng


def _session(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _write_minimal_sample(parent: Path, sample_id: str) -> Path:
    """Write the smallest legal sample.toml under ``parent / sample_id``.

    Centralised so a schema rev to ``[sample]`` only touches one place.
    """
    d = parent / sample_id
    d.mkdir()
    (d / "sample.toml").write_text(
        '[sample]\ndata_source = "experimental"\nproject = "chromatin"\n'
    )
    return d


def test_scan_fixture_root_happy_path(engine):
    report = scanner.scan_root(engine, FIXTURES)
    assert report.upserted == 2  # sample_chromatin + sample_simulation
    assert report.skipped == 0
    assert report.errors == []

    s = _session(engine)
    try:
        # Both sample rows present
        sample_ids = {
            row[0] for row in s.execute(select(orm.SampleORM.sample_id)).all()
        }
        assert sample_ids == {"sample_chromatin", "sample_simulation"}

        # Position_86 + Position_87 acquisitions present
        acqs = (
            s.execute(
                select(orm.AcquisitionORM).where(
                    orm.AcquisitionORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert {a.acquisition_id for a in acqs} == {"Position_86", "Position_87"}

        # Raw tomogram row written (sample_chromatin fixture uses [raw_tomogram])
        # with MRC + zarr-derived dimensions populated by the assembler.
        tomos = (
            s.execute(
                select(orm.RawTomogramORM).where(
                    orm.RawTomogramORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert {t.tomogram_id for t in tomos} == {"bp_3dctf_bin4"}
        tomo = tomos[0]
        assert tomo.image_size_x == 4
        assert tomo.mrc_path is not None
        assert tomo.zarr_path is not None

        # Annotation row populated with discovered files
        anns = (
            s.execute(
                select(orm.AnnotationORM).where(
                    orm.AnnotationORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        assert len(anns) == 1
        assert any(p.endswith("segmentation.mrc") for p in anns[0].files)

        # scans row written, status='completed'
        scans = s.execute(select(orm.ScansORM)).scalars().all()
        assert len(scans) == 1
        assert scans[0].status == "completed"
        assert scans[0].samples_upserted == 2

        # catalog_meta row reflects the root we just scanned
        meta = s.get(orm.CatalogMetaORM, 1)
        assert meta is not None
        assert meta.data_root == str(FIXTURES.resolve())

        # scan_warnings: at least one for Position_87 (missing_acquisition_toml)
        warnings = (
            s.execute(
                select(orm.ScanWarningsORM).where(
                    orm.ScanWarningsORM.sample_id == "sample_chromatin"
                )
            )
            .scalars()
            .all()
        )
        categories = {w.category for w in warnings}
        assert "missing_acquisition_toml" in categories
        # All warning rows from this scan share scan_run_id
        scan_run_ids = {w.scan_run_id for w in warnings}
        assert len(scan_run_ids) == 1
    finally:
        s.close()


def test_second_scan_skips_unchanged_samples(engine):
    scanner.scan_root(engine, FIXTURES)
    report2 = scanner.scan_root(engine, FIXTURES)
    assert report2.upserted == 0
    assert report2.skipped == 2
    assert report2.errors == []


def test_force_bypasses_gate(engine):
    scanner.scan_root(engine, FIXTURES)
    report = scanner.scan_root(engine, FIXTURES, force=True)
    assert report.upserted == 2
    assert report.skipped == 0


def test_touched_file_triggers_reassemble(engine):
    scanner.scan_root(engine, FIXTURES)
    target = FIXTURES / "sample_chromatin" / "sample.toml"
    original_mtime = target.stat().st_mtime
    new_mtime = original_mtime + 100
    os.utime(target, (new_mtime, new_mtime))
    try:
        report = scanner.scan_root(engine, FIXTURES)
        # sample_chromatin should be re-assembled, sample_simulation skipped
        assert report.upserted >= 1
        assert report.skipped >= 1
    finally:
        # Restore mtime so other tests aren't affected
        os.utime(target, (original_mtime, original_mtime))


def test_two_scans_make_two_scans_rows(engine):
    scanner.scan_root(engine, FIXTURES)
    scanner.scan_root(engine, FIXTURES)
    s = _session(engine)
    try:
        scans = s.execute(select(orm.ScansORM)).scalars().all()
        assert len(scans) == 2
        assert all(sc.status == "completed" for sc in scans)
    finally:
        s.close()


def test_prune_dry_run_reports_without_writing(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")
    sample_b = _write_minimal_sample(tmp_path, "sample_b")

    scanner.scan_root(engine, tmp_path)

    # Now remove sample_b on disk
    (sample_b / "sample.toml").unlink()
    sample_b.rmdir()

    # Dry run prune
    report = scanner.scan_root(
        engine,
        tmp_path,
        prune=False,
        prune_dry_run=True,
        prune_safety_floor=1.0,
    )
    assert report.would_soft_delete == ["sample_b"]

    # sample_b is NOT actually soft-deleted yet
    s = _session(engine)
    try:
        b = s.get(orm.SampleORM, "sample_b")
        assert b is not None
        assert b.deleted_at is None
    finally:
        s.close()


def test_prune_actually_soft_deletes(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")
    sample_b = _write_minimal_sample(tmp_path, "sample_b")

    scanner.scan_root(engine, tmp_path)

    # Remove sample_b
    (sample_b / "sample.toml").unlink()
    sample_b.rmdir()

    report = scanner.scan_root(
        engine, tmp_path, prune=True, prune_safety_floor=1.0
    )
    assert report.soft_deleted == 1

    s = _session(engine)
    try:
        b = s.get(orm.SampleORM, "sample_b")
        assert b is not None
        assert b.deleted_at is not None
    finally:
        s.close()


def test_resurrected_sample_reassembled_even_if_unchanged(engine, tmp_path):
    _write_minimal_sample(tmp_path, "sample_a")

    # First scan
    scanner.scan_root(engine, tmp_path)

    # Mark soft-deleted manually (simulates a prior prune)
    s = _session(engine)
    try:
        s.execute(
            orm.SampleORM.__table__.update()
            .where(orm.SampleORM.sample_id == "sample_a")
            .values(deleted_at=time.time())
        )
        s.commit()
    finally:
        s.close()

    # Re-scan: file is unchanged on disk so the gate would normally skip,
    # but soft-deleted samples must be re-assembled to clear the tombstone.
    report = scanner.scan_root(engine, tmp_path)
    assert report.upserted == 1
    assert report.skipped == 0

    s = _session(engine)
    try:
        a = s.get(orm.SampleORM, "sample_a")
        assert a is not None
        assert a.deleted_at is None  # resurrected
    finally:
        s.close()


def test_failed_scan_marks_status_failed(engine, tmp_path):
    sample_a = _write_minimal_sample(tmp_path, "sample_a")

    # First scan succeeds.
    scanner.scan_root(engine, tmp_path)

    # Rename the sample dir so the on-disk sample_id changes; the original
    # sample_a row in the DB now has no fs match. With safety_floor=0.0 the
    # prune step will exceed the floor and raise.
    sample_a.rename(tmp_path / "renamed_a")

    with pytest.raises(Exception):
        scanner.scan_root(
            engine, tmp_path, prune=True, prune_safety_floor=0.0
        )

    s = _session(engine)
    try:
        scans = (
            s.execute(
                select(orm.ScansORM).order_by(orm.ScansORM.started_at.desc())
            )
            .scalars()
            .all()
        )
        # Most recent scan should be 'failed'
        assert scans[0].status == "failed"
    finally:
        s.close()


def test_scan_populates_disk_size_bytes(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    # Add a file with a known size so dir_size_bytes returns something non-zero.
    (sample_dir / "data.bin").write_bytes(b"x" * 1024)

    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.disk_size_bytes is not None
        assert row.disk_size_bytes == discovery.dir_size_bytes(sample_dir)
    finally:
        s.close()


def test_skip_preserves_disk_size_bytes(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    (sample_dir / "data.bin").write_bytes(b"x" * 1024)

    # First scan: populates disk_size_bytes.
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        original_size = row.disk_size_bytes
        assert original_size is not None
    finally:
        s.close()

    # Second scan: nothing changed on disk, so the mtime gate skips the sample.
    report2 = scanner.scan_root(engine, tmp_path)
    assert report2.skipped >= 1

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.disk_size_bytes == original_size
    finally:
        s.close()


def test_force_recomputes_disk_size_bytes(engine, tmp_path):
    sample_dir = _write_minimal_sample(tmp_path, "sample_a")
    (sample_dir / "data.bin").write_bytes(b"x" * 1024)

    # First scan.
    scanner.scan_root(engine, tmp_path)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        first_size = row.disk_size_bytes
        assert first_size is not None
    finally:
        s.close()

    # Add a new file to increase the on-disk size.
    extra_file = sample_dir / "extra.bin"
    extra_file.write_bytes(b"y" * 512)
    extra_bytes = extra_file.stat().st_size

    # Re-scan with force=True so it re-assembles and recomputes size.
    scanner.scan_root(engine, tmp_path, force=True)

    s = _session(engine)
    try:
        row = s.get(orm.SampleORM, "sample_a")
        assert row is not None
        assert row.disk_size_bytes is not None
        assert row.disk_size_bytes >= first_size + extra_bytes
    finally:
        s.close()
