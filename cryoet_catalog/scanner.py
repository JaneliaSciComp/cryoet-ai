"""Scanner orchestrator.

scan_root walks the data root, runs the gating check, dispatches per-sample
to the assembler + persistence layer inside a transaction, and tracks the
overall run via the `scans` table (one row per invocation, status running/
completed/failed) and a per-sample ScanReport returned to the caller.

Single-writer contract: running two scan_root calls against the same
DB simultaneously is undefined. The CLI takes no advisory lock; the operator
is responsible for serializing scans.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from cryoet_catalog import assembler, discovery, orm, persistence, state, thumbnails
from cryoet_catalog.assembler import FieldConflict, ScanWarning


@dataclass
class ScanReport:
    upserted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[ScanWarning] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)
    soft_deleted: int = 0
    # populated only on prune_dry_run=True
    would_soft_delete: list[str] | None = None
    # Per-sample membership behind the counts above, persisted to scan_samples
    # so the /manage view can list which samples sit behind each tally.
    upserted_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    # (sample_id, error message) — sample-level failures only.
    failed_samples: list[tuple[str, str]] = field(default_factory=list)
    thumbnails_healed: int = 0


def scan_root(
    engine: Engine,
    root: Path,
    *,
    force: bool = False,
    prune: bool = False,
    prune_dry_run: bool = False,
    prune_safety_floor: float = 0.5,
    on_error: Literal["collect", "raise"] = "collect",
    thumbnail_dir: Path | None = None,
) -> ScanReport:
    """Walk ``root``, assemble + persist each sample, return a ScanReport.

    Mtime gating: a sample is skipped if every parse-target file's mtime is
    unchanged AND the parse-target set is unchanged AND the sample is not
    soft-deleted. ``force=True`` bypasses the gate.

    ``prune=True`` runs ``soft_delete_missing_samples`` after the per-sample
    loop. ``prune_dry_run=True`` reports what would be deleted without writing.
    ``prune_safety_floor`` (0..1.0) caps the fraction of live samples that may
    be deleted in one run; raise PruneSafetyFloorExceeded otherwise.

    ``on_error='collect'`` records sample-level exceptions to ``report.errors``
    and continues. ``'raise'`` propagates the first exception.
    """
    SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    report = ScanReport()
    scan_run_id = uuid4().hex

    session = SessionFactory()
    try:
        # Open scan_run + catalog_meta in their own transaction so they're
        # visible to subsequent transactions.
        with session.begin():
            state.start_scan(session, scan_run_id, root)

        # One SELECT before the loop for soft-deleted ids.
        with session.begin():
            soft_deleted_ids = state.load_soft_deleted_ids(session)

        fs_sample_ids: set[str] = set()
        for sample_loc in discovery.iter_samples(root):
            fs_sample_ids.add(sample_loc.sample_id)

            # Per-sample work in its own transaction
            try:
                _scan_one_sample(
                    session,
                    sample_loc,
                    force=force,
                    soft_deleted_ids=soft_deleted_ids,
                    scan_run_id=scan_run_id,
                    report=report,
                    thumbnail_dir=thumbnail_dir,
                )
            except Exception as e:  # noqa: BLE001
                # Make sure no partial transaction is left dangling.
                if session.in_transaction():
                    session.rollback()
                report.errors.append(f"{sample_loc.sample_id}: {e}")
                report.failed_samples.append((sample_loc.sample_id, str(e)))
                if on_error == "raise":
                    raise

        # After the loop: optional prune
        if prune or prune_dry_run:
            with session.begin():
                try:
                    persistence.soft_delete_missing_samples(
                        session,
                        fs_sample_ids,
                        dry_run=prune_dry_run,
                        safety_floor=prune_safety_floor,
                        report=report,
                    )
                except persistence.PruneSafetyFloorExceeded as exc:
                    report.errors.append(
                        f"prune aborted: would soft-delete {len(exc.missing)} "
                        f"samples ({exc.ratio:.1%} > floor "
                        f"{exc.threshold:.1%}); missing={exc.missing}"
                    )
                    raise

        with session.begin():
            state.finish_scan(
                session, scan_run_id, status="completed", report=report
            )
    except Exception:
        # Mark the scan failed; let the exception propagate per on_error semantics.
        try:
            if session.in_transaction():
                session.rollback()
            with session.begin():
                state.finish_scan(
                    session, scan_run_id, status="failed", report=report
                )
        except Exception:
            pass  # don't mask the original
        raise
    finally:
        session.close()

    return report


def _scan_one_sample(
    session,
    sample_loc,
    *,
    force: bool,
    soft_deleted_ids: set[str],
    scan_run_id: str,
    report: ScanReport,
    thumbnail_dir: Path | None,
) -> None:
    """Per-sample scan inside its own transaction. Mutates ``report`` in place."""
    parse_targets = discovery.parse_targets_for_sample(sample_loc)

    # Gating check (read state in its own short transaction)
    with session.begin():
        sample_state = state.load_sample_state(session, sample_loc.sample_id)

    is_soft_deleted = sample_loc.sample_id in soft_deleted_ids
    if (
        not force
        and not is_soft_deleted
        and not state.parse_target_set_changed(sample_state, parse_targets)
        and not any(state.is_file_changed(sample_state, p) for p in parse_targets)
    ):
        if thumbnail_dir is not None:
            with session.begin():
                stored = session.get(orm.SampleORM, sample_loc.sample_id)
                rel = stored.thumbnail_path if stored else None
                if rel and not (thumbnail_dir / rel).is_file():
                    new_rel = thumbnails.generate_thumbnails(
                        sample_loc.sample_id,
                        thumbnails.refs_from_db(session, sample_loc.sample_id),
                        thumbnail_dir,
                        skip_existing=True,
                    )
                    stored.thumbnail_path = new_rel
                    session.add(stored)
                    report.thumbnails_healed += 1
        report.skipped += 1
        report.skipped_ids.append(sample_loc.sample_id)
        return

    # Assemble + persist in one transaction
    with session.begin():
        result = assembler.assemble_sample(sample_loc)
        report.warnings.extend(result.warnings)
        report.conflicts.extend(result.conflicts)

        if result.record is None:
            report.errors.extend(
                f"{sample_loc.sample_id}: {e}" for e in result.errors
            )
            report.failed_samples.append(
                (sample_loc.sample_id, "; ".join(result.errors))
            )
            return
        for e in result.errors:
            report.errors.append(f"{sample_loc.sample_id}: {e}")

        disk_size = discovery.dir_size_bytes(sample_loc.path)
        thumb_rel = None
        if thumbnail_dir is not None:
            thumb_rel = thumbnails.generate_thumbnails(
                sample_loc.sample_id,
                thumbnails.refs_from_record(result.record),
                thumbnail_dir,
                skip_existing=False,
            )
        persistence.upsert_sample_record(
            session,
            result.record,
            extras=result.extras,
            warnings=result.warnings,
            scan_run_id=scan_run_id,
            disk_size_bytes=disk_size,
            thumbnail_path=thumb_rel,
        )
        # Update mtime state for every parse target.
        for p in parse_targets:
            try:
                mtime = p.stat().st_mtime
            except FileNotFoundError:
                continue  # file disappeared between discovery and stat — skip
            state.record_file_scan(session, p, sample_loc.sample_id, mtime)
        # Prune scan_state rows for files that are no longer parse targets.
        state.prune_missing(
            session, sample_loc.sample_id, kept_paths=set(parse_targets)
        )
        report.upserted += 1
        report.upserted_ids.append(sample_loc.sample_id)


__all__ = ["ScanReport", "scan_root"]
