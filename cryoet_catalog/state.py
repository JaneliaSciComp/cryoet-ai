"""DB helpers for mtime gating and scan tracking (per §4.5 of the plan).

Pure path → mtime comparison and small SQL upserts; no orchestration logic
lives here. The orchestrator (scanner.py) loads the per-sample state once, then
walks parse targets through ``is_file_changed`` in Python.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from cryoet_catalog.orm import (
    CatalogMetaORM,
    SampleORM,
    ScansORM,
    ScanSamplesORM,
    ScanStateORM,
)


def load_sample_state(session: Session, sample_id: str) -> dict[Path, float]:
    """Return ``{Path: mtime}`` for every scan_state row for this sample.

    Implemented as one indexed SELECT (sample_id is indexed in the ORM).
    """
    rows = session.execute(
        select(ScanStateORM.path, ScanStateORM.mtime).where(
            ScanStateORM.sample_id == sample_id
        )
    ).all()
    return {Path(p): m for p, m in rows}


def is_file_changed(state: dict[Path, float], path: Path) -> bool:
    """Stat ``path`` and compare its mtime to ``state.get(path)``.

    Returns True if the path is missing from state (first-seen) or its mtime
    differs from the recorded value. A missing file on disk also counts as
    "changed" — the orchestrator will re-assemble and pruning will drop the
    stale row.
    """
    try:
        current = path.stat().st_mtime
    except FileNotFoundError:
        return True
    prev = state.get(path)
    return prev is None or prev != current


def record_file_scan(
    session: Session, path: Path, sample_id: str, mtime: float
) -> None:
    """Upsert ``scan_state(path, sample_id, mtime, last_scanned=now)``."""
    now = time.time()
    existing = session.get(ScanStateORM, str(path))
    if existing is None:
        session.add(
            ScanStateORM(
                path=str(path),
                sample_id=sample_id,
                mtime=mtime,
                last_scanned=now,
                content_hash=None,
            )
        )
    else:
        existing.mtime = mtime
        existing.last_scanned = now
        existing.sample_id = sample_id  # in case of moves


def parse_target_set_changed(
    state: dict[Path, float], parse_targets: list[Path]
) -> bool:
    """True iff ``set(parse_targets) != set(state.keys())``.

    Detects files added or removed since the last scan; mtime drift on
    individual files is handled by ``is_file_changed``.
    """
    return set(parse_targets) != set(state.keys())


def prune_missing(
    session: Session, sample_id: str, kept_paths: set[Path]
) -> int:
    """Delete every ``scan_state`` row for this sample whose path is not in
    ``kept_paths``. Returns the count of rows deleted.
    """
    kept_str = {str(p) for p in kept_paths}
    rows = (
        session.execute(
            select(ScanStateORM.path).where(ScanStateORM.sample_id == sample_id)
        )
        .scalars()
        .all()
    )
    to_delete = [p for p in rows if p not in kept_str]
    if not to_delete:
        return 0
    result = session.execute(
        delete(ScanStateORM)
        .where(ScanStateORM.sample_id == sample_id)
        .where(ScanStateORM.path.in_(to_delete))
    )
    return result.rowcount or 0


def load_soft_deleted_ids(session: Session) -> set[str]:
    """Return the set of sample_ids currently soft-deleted.

    Called once at the top of ``scan_root`` so the per-sample gating loop can
    force re-assembly for any soft-deleted sample whose dir has reappeared on
    disk — without this, mtime-unchanged files would skip gating and leave
    ``deleted_at`` set forever.
    """
    rows = (
        session.execute(
            select(SampleORM.sample_id).where(SampleORM.deleted_at.is_not(None))
        )
        .scalars()
        .all()
    )
    return set(rows)


def start_scan(session: Session, scan_run_id: str, root: Path) -> None:
    """Record the start of a scan run and upsert ``catalog_meta.data_root``.

    The ``catalog_meta`` upsert lives here (rather than in ``finish_scan``)
    so the table reflects what root *was being scanned* even if the scan
    crashes before completing.
    """
    now = time.time()
    session.add(
        ScansORM(
            scan_run_id=scan_run_id,
            started_at=now,
            ended_at=None,
            root=str(root),
            status="running",
            samples_upserted=None,
            samples_skipped=None,
            samples_failed=None,
        )
    )
    existing = session.get(CatalogMetaORM, 1)
    if existing is None:
        session.add(
            CatalogMetaORM(id=1, data_root=str(root), updated_at=now)
        )
    else:
        existing.data_root = str(root)
        existing.updated_at = now


def finish_scan(
    session: Session,
    scan_run_id: str,
    *,
    status: str,
    report: Any,
) -> None:
    """Mark a scan run as finished and record the per-sample tallies.

    ``report`` is duck-typed: any object with ``upserted``, ``skipped``, and
    ``errors`` attributes works (the real ``ScanReport`` lives in §4.8). We
    use ``getattr`` with safe defaults so an early-failure caller can still
    call this with a stub.
    """
    now = time.time()
    upserted = getattr(report, "upserted", 0) or 0
    skipped = getattr(report, "skipped", 0) or 0
    failed = len(getattr(report, "errors", []) or [])
    session.execute(
        update(ScansORM)
        .where(ScansORM.scan_run_id == scan_run_id)
        .values(
            ended_at=now,
            status=status,
            samples_upserted=upserted,
            samples_skipped=skipped,
            samples_failed=failed,
        )
    )
    _record_scan_membership(session, scan_run_id, report)


def _record_scan_membership(
    session: Session, scan_run_id: str, report: Any
) -> None:
    """Persist which samples were upserted/skipped/failed for this run.

    Idempotent: clears any prior rows for ``scan_run_id`` first, so the
    failure path (``finish_scan`` called twice) doesn't double-insert.
    Failed samples are deduplicated by ``sample_id`` (a single sample can
    surface multiple error strings).
    """
    session.execute(
        delete(ScanSamplesORM).where(ScanSamplesORM.scan_run_id == scan_run_id)
    )

    for sample_id in getattr(report, "upserted_ids", []) or []:
        session.add(
            ScanSamplesORM(
                scan_run_id=scan_run_id, sample_id=sample_id, outcome="upserted"
            )
        )
    for sample_id in getattr(report, "skipped_ids", []) or []:
        session.add(
            ScanSamplesORM(
                scan_run_id=scan_run_id, sample_id=sample_id, outcome="skipped"
            )
        )
    seen_failed: set[str] = set()
    for sample_id, detail in getattr(report, "failed_samples", []) or []:
        if sample_id in seen_failed:
            continue
        seen_failed.add(sample_id)
        session.add(
            ScanSamplesORM(
                scan_run_id=scan_run_id,
                sample_id=sample_id,
                outcome="failed",
                detail=detail or None,
            )
        )
