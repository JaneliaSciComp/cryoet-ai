"""Persistence: turn an AssemblyResult into rows in the catalog DB.

The persistence layer is dumb in two senses:
1. It never re-derives field values — whatever the assembler put on the record
   is what gets written.
2. It never re-walks the SampleRecord for extras — the structured ExtrasEntry
   list from schema.loader (passed through AssemblyResult.extras) is
   the single source of truth for the extras table.

A scan_run_id is supplied by the orchestrator; persistence stamps detected_at
and scan_run_id on each scan_warnings row at insert time.

Upserts use ``session.merge()`` for cross-dialect portability (SQLite +
Postgres). All operations for one sample happen inside one transaction (the
orchestrator opens ``session.begin()`` around the call); on exception the
transaction rolls back and the orchestrator records the sample as failed.
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import Session

from schema import SampleRecord
from schema.loader import ExtrasEntry

from catalog import orm
from catalog.assembler import ScanWarning


class PruneSafetyFloorExceeded(Exception):
    """Raised when soft_delete_missing_samples would delete more than the
    configured fraction of currently-live samples.

    Attributes
    ----------
    missing : list[str]
        Sample IDs that would be soft-deleted.
    threshold : float
        The configured safety-floor ratio (0.0 - 1.0).
    ratio : float
        The actual ratio that triggered the abort.
    """

    def __init__(self, missing: list[str], threshold: float, ratio: float) -> None:
        self.missing = missing
        self.threshold = threshold
        self.ratio = ratio
        super().__init__(
            f"safety floor exceeded: would soft-delete {len(missing)} sample(s) "
            f"({ratio:.1%} > {threshold:.1%})"
        )


# ─── helpers ─────────────────────────────────────────────────────────────────


def _filter_to_columns(payload: dict, orm_cls) -> dict:
    """Drop keys from ``payload`` that aren't columns on ``orm_cls``.

    Lets us pass Pydantic dumps that may include nested-model values or other
    keys without SQLAlchemy raising on unknown columns.
    """
    columns = {c.name for c in orm_cls.__table__.columns}
    return {k: v for k, v in payload.items() if k in columns}


def _json_safe(o: Any) -> Any:
    """``json.dumps`` default function — handles ``date``/``datetime`` etc."""
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _upsert_or_delete_sub(
    session: Session, orm_cls, sample_id: str, pyd_model
) -> None:
    """1:1 sub-entity upsert-or-delete (sample-scoped).

    If ``pyd_model`` is None, DELETE the row (clears stale data when a TOML
    block is removed); otherwise upsert via ``session.merge()``.
    """
    if pyd_model is None:
        session.execute(delete(orm_cls).where(orm_cls.sample_id == sample_id))
        return
    payload = pyd_model.model_dump(exclude_none=False)
    payload["sample_id"] = sample_id
    session.merge(orm_cls(**_filter_to_columns(payload, orm_cls)))


def _delete_stale_children(
    session: Session,
    orm_cls,
    sample_id: str,
    *,
    pk_cols: tuple[str, ...],
    keep: set[tuple],
) -> None:
    """Delete child rows for ``sample_id`` whose PK tuple isn't in ``keep``.

    We do a SELECT of existing rows + Python diff against the in-memory keep
    set rather than ``NOT IN (subquery)`` because the merge() inserts in this
    same transaction may not be flushed/visible to a SELECT yet.
    """
    rows = session.execute(
        select(*[getattr(orm_cls, c) for c in pk_cols]).where(
            orm_cls.sample_id == sample_id
        )
    ).all()
    to_delete = [tuple(r) for r in rows if tuple(r) not in keep]
    for pk_tuple in to_delete:
        stmt = delete(orm_cls)
        for col, val in zip(pk_cols, pk_tuple):
            stmt = stmt.where(getattr(orm_cls, col) == val)
        session.execute(stmt)


# ─── main entry point ────────────────────────────────────────────────────────


def upsert_sample_record(
    session: Session,
    record: SampleRecord,
    *,
    extras: list[ExtrasEntry],
    warnings: list[ScanWarning],
    scan_run_id: str,
    disk_size_bytes: int | None = None,
    thumbnail_path: str | None = None,
) -> None:
    """Per-sample upsert. Steps:

    1. ``samples`` row from ``record.sample`` (clear ``deleted_at`` on
       resurrection).
    2. 1:1 sub-entities upsert-or-delete (chromatin, fiducial, simulation,
       freezing, milling).
    3. ``labels`` ordinal upsert + clean rows with ordinal >= len(record.label).
    4. ``md_runs`` upsert + stale-row cleanup (keyed by md_run_id).
    5. Per-acquisition: ``acquisitions`` upsert, ``md_source`` 1:1
       upsert-or-delete (scoped by acq), ``raw_tomograms`` /
       ``post_processed_tomograms`` / ``annotations`` / ``tilt_series``
       upsert.
    6. ``extras`` refresh: DELETE WHERE sample_id = ? then INSERT fresh.
    7. ``scan_warnings`` refresh: DELETE WHERE sample_id = ? then INSERT
       fresh with ``detected_at`` and ``scan_run_id`` stamped.
    8. Stale-row cleanup for the multi-row child tables using Python keep-sets.
    """
    sample_id = record.sample.sample_id
    assert sample_id is not None, (
        "sample_id must be set on the record before persistence"
    )

    now = time.time()

    # ---- Step 1: samples row ------------------------------------------------
    sample_payload = record.sample.model_dump(exclude_none=False)
    # Resurrect on every upsert — if the row was previously soft-deleted, the
    # filesystem reappearing must clear the tombstone.
    sample_payload["deleted_at"] = None
    sample_payload["disk_size_bytes"] = disk_size_bytes
    sample_payload["thumbnail_path"] = thumbnail_path
    session.merge(
        orm.SampleORM(**_filter_to_columns(sample_payload, orm.SampleORM))
    )

    # ---- Step 2: 1:1 sub-entities ------------------------------------------
    _upsert_or_delete_sub(session, orm.ChromatinORM, sample_id, record.chromatin)
    _upsert_or_delete_sub(session, orm.FiducialORM, sample_id, record.fiducial)
    _upsert_or_delete_sub(session, orm.SimulationORM, sample_id, record.simulation)
    _upsert_or_delete_sub(session, orm.FreezingORM, sample_id, record.freezing)
    _upsert_or_delete_sub(session, orm.MillingORM, sample_id, record.milling)

    # ---- Step 3: labels (ordinal-keyed list) -------------------------------
    for ordinal, label_model in enumerate(record.label):
        payload = label_model.model_dump(exclude_none=False)
        payload["sample_id"] = sample_id
        payload["ordinal"] = ordinal
        session.merge(orm.LabelORM(**_filter_to_columns(payload, orm.LabelORM)))
    # Clean up trailing ordinals.
    session.execute(
        delete(orm.LabelORM)
        .where(orm.LabelORM.sample_id == sample_id)
        .where(orm.LabelORM.ordinal >= len(record.label))
    )

    # ---- Step 4: md_runs (id-keyed list) -----------------------------------
    keep_md_run_pks: set[tuple[str, str]] = set()
    for run in record.md_run:
        # by_alias=False so the dump uses ``md_run_id`` (the field name),
        # matching the ORM column. The schema field has alias ``id``.
        payload = run.model_dump(exclude_none=False, by_alias=False)
        payload["sample_id"] = sample_id
        session.merge(orm.MdRunORM(**_filter_to_columns(payload, orm.MdRunORM)))
        keep_md_run_pks.add((sample_id, run.md_run_id))

    # ---- Step 5: per-acquisition fan-out -----------------------------------
    keep_acq_pks: set[tuple[str, str]] = set()
    keep_md_source_pks: set[tuple[str, str]] = set()
    keep_raw_tomo_pks: set[tuple[str, str, str]] = set()
    keep_post_tomo_pks: set[tuple[str, str, str]] = set()
    keep_ann_pks: set[tuple[str, str, str]] = set()
    keep_ts_pks: set[tuple[str, str, str]] = set()

    for acq_id, acq_file in record.acquisitions.items():
        acq_payload = acq_file.acquisition.model_dump(
            exclude_none=False, by_alias=False
        )
        acq_payload["sample_id"] = sample_id
        # acquisition_id is Optional on the Pydantic model but PK on the
        # DB; the dict-key from the SampleRecord is authoritative.
        acq_payload["acquisition_id"] = acq_id
        session.merge(
            orm.AcquisitionORM(
                **_filter_to_columns(acq_payload, orm.AcquisitionORM)
            )
        )
        keep_acq_pks.add((sample_id, acq_id))

        # md_source is 1:1 per acquisition. Delete on absence, upsert on
        # presence — scoped to this single (sample_id, acquisition_id) so we
        # don't clobber siblings.
        if acq_file.md_source is None:
            session.execute(
                delete(orm.MdSourceORM).where(
                    and_(
                        orm.MdSourceORM.sample_id == sample_id,
                        orm.MdSourceORM.acquisition_id == acq_id,
                    )
                )
            )
        else:
            md_payload = acq_file.md_source.model_dump(exclude_none=False)
            md_payload["sample_id"] = sample_id
            md_payload["acquisition_id"] = acq_id
            session.merge(
                orm.MdSourceORM(
                    **_filter_to_columns(md_payload, orm.MdSourceORM)
                )
            )
            keep_md_source_pks.add((sample_id, acq_id))

        if acq_file.raw_tomogram is not None:
            raw = acq_file.raw_tomogram
            raw_payload = raw.model_dump(exclude_none=False, by_alias=False)
            raw_payload["sample_id"] = sample_id
            raw_payload["acquisition_id"] = acq_id
            session.merge(
                orm.RawTomogramORM(
                    **_filter_to_columns(raw_payload, orm.RawTomogramORM)
                )
            )
            keep_raw_tomo_pks.add((sample_id, acq_id, raw.tomogram_id))

        for tomo in acq_file.post_processed_tomogram:
            tomo_payload = tomo.model_dump(exclude_none=False, by_alias=False)
            tomo_payload["sample_id"] = sample_id
            tomo_payload["acquisition_id"] = acq_id
            session.merge(
                orm.PostProcessedTomogramORM(
                    **_filter_to_columns(
                        tomo_payload, orm.PostProcessedTomogramORM
                    )
                )
            )
            keep_post_tomo_pks.add((sample_id, acq_id, tomo.tomogram_id))

        for ann in acq_file.annotation:
            ann_payload = ann.model_dump(exclude_none=False, by_alias=False)
            ann_payload["sample_id"] = sample_id
            ann_payload["acquisition_id"] = acq_id
            session.merge(
                orm.AnnotationORM(
                    **_filter_to_columns(ann_payload, orm.AnnotationORM)
                )
            )
            keep_ann_pks.add((sample_id, acq_id, ann.annotation_id))

        for ts in acq_file.tilt_series:
            # ``tilt_series_id`` is required at the DB level (composite PK)
            # but Optional on the Pydantic model. The scanner always sets
            # it; defensive skip on None preserves the invariant.
            if ts.tilt_series_id is None:
                continue
            ts_payload = ts.model_dump(exclude_none=False, by_alias=False)
            ts_payload["sample_id"] = sample_id
            ts_payload["acquisition_id"] = acq_id
            session.merge(
                orm.TiltSeriesORM(
                    **_filter_to_columns(ts_payload, orm.TiltSeriesORM)
                )
            )
            keep_ts_pks.add((sample_id, acq_id, ts.tilt_series_id))

    # ---- Step 8: stale-row cleanup for multi-row child tables -------------
    _delete_stale_children(
        session,
        orm.MdRunORM,
        sample_id,
        pk_cols=("sample_id", "md_run_id"),
        keep=keep_md_run_pks,
    )
    _delete_stale_children(
        session,
        orm.AcquisitionORM,
        sample_id,
        pk_cols=("sample_id", "acquisition_id"),
        keep=keep_acq_pks,
    )
    _delete_stale_children(
        session,
        orm.MdSourceORM,
        sample_id,
        pk_cols=("sample_id", "acquisition_id"),
        keep=keep_md_source_pks,
    )
    _delete_stale_children(
        session,
        orm.RawTomogramORM,
        sample_id,
        pk_cols=("sample_id", "acquisition_id", "tomogram_id"),
        keep=keep_raw_tomo_pks,
    )
    _delete_stale_children(
        session,
        orm.PostProcessedTomogramORM,
        sample_id,
        pk_cols=("sample_id", "acquisition_id", "tomogram_id"),
        keep=keep_post_tomo_pks,
    )
    _delete_stale_children(
        session,
        orm.AnnotationORM,
        sample_id,
        pk_cols=("sample_id", "acquisition_id", "annotation_id"),
        keep=keep_ann_pks,
    )
    _delete_stale_children(
        session,
        orm.TiltSeriesORM,
        sample_id,
        pk_cols=("sample_id", "acquisition_id", "tilt_series_id"),
        keep=keep_ts_pks,
    )

    # ---- Step 6: extras refresh -------------------------------------------
    session.execute(
        delete(orm.ExtrasORM).where(orm.ExtrasORM.sample_id == sample_id)
    )
    for entry in extras:
        session.add(
            orm.ExtrasORM(
                entity_type=entry.entity_type,
                entity_pk_json=json.dumps(list(entry.entity_pk)),
                key=entry.key,
                # Denormalized — by construction equal to sample_id.
                sample_id=entry.entity_pk[0],
                value_json=json.dumps(entry.value, default=_json_safe),
            )
        )

    # ---- Step 7: scan_warnings refresh ------------------------------------
    session.execute(
        delete(orm.ScanWarningsORM).where(
            orm.ScanWarningsORM.sample_id == sample_id
        )
    )
    for w in warnings:
        session.add(
            orm.ScanWarningsORM(
                sample_id=sample_id,
                category=w.category,
                location=w.location,
                message=w.message,
                detected_at=now,
                scan_run_id=scan_run_id,
            )
        )


# ─── soft delete + safety floor ──────────────────────────────────────────────


def soft_delete_missing_samples(
    session: Session,
    fs_sample_ids: set[str],
    *,
    dry_run: bool = False,
    safety_floor: float = 0.5,
    report=None,
) -> None:
    """Diff ``fs_sample_ids`` against currently-live samples in the DB.

    - Live samples are those with ``deleted_at IS NULL``.
    - If the prune fraction would exceed ``safety_floor`` (and there is at
      least one live sample), raise :class:`PruneSafetyFloorExceeded` —
      this is checked before either dry-run reporting or writes.
    - On ``dry_run``: append the would-delete IDs to
      ``report.would_soft_delete`` (if a report is provided) and return
      without writing.
    - Otherwise: ``UPDATE samples SET deleted_at = ? WHERE sample_id IN ?``.

    Child entities are intentionally NOT touched: soft delete preserves
    history so a sample can be resurrected by a later upsert.
    """
    live_rows = (
        session.execute(
            select(orm.SampleORM.sample_id).where(
                orm.SampleORM.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    live = set(live_rows)
    to_delete = sorted(live - fs_sample_ids)

    if not to_delete:
        return

    if live:
        ratio = len(to_delete) / len(live)
        if ratio > safety_floor:
            raise PruneSafetyFloorExceeded(
                missing=to_delete, threshold=safety_floor, ratio=ratio
            )

    if dry_run:
        if report is not None:
            existing = getattr(report, "would_soft_delete", None)
            if existing is None:
                report.would_soft_delete = []
            report.would_soft_delete.extend(to_delete)
        return

    now = time.time()
    session.execute(
        update(orm.SampleORM)
        .where(orm.SampleORM.sample_id.in_(to_delete))
        .values(deleted_at=now)
    )
    if report is not None:
        report.soft_deleted = getattr(report, "soft_deleted", 0) + len(to_delete)


__all__ = [
    "PruneSafetyFloorExceeded",
    "soft_delete_missing_samples",
    "upsert_sample_record",
]
