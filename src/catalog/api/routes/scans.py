"""GET /scans, /scans/latest, /scans/latest/warnings, /scans/latest/run-warnings,
/scans/latest/samples, /scans/{scan_run_id}, /scans/{scan_run_id}/warnings,
/scans/{scan_run_id}/run-warnings, /scans/{scan_run_id}/samples."""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.schemas import (
    RunWarningOut,
    ScanOut,
    ScanSampleOut,
    SampleWarningsGroup,
)

router = APIRouter()

Outcome = Literal["upserted", "skipped", "failed"]


def _enum_val(v):
    """Coerce a possibly-enum value to its string value."""
    return v.value if hasattr(v, "value") else v


def _latest_completed_scan_id(session: Session) -> str | None:
    """scan_run_id of the most recent completed scan, or None if there is none."""
    return session.execute(
        select(orm.ScansORM.scan_run_id)
        .where(orm.ScansORM.status == "completed")
        .order_by(orm.ScansORM.ended_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _to_out(row: orm.ScansORM) -> ScanOut:
    return ScanOut(
        scan_run_id=row.scan_run_id,
        started_at=row.started_at, ended_at=row.ended_at,
        root=row.root, status=row.status,
        samples_upserted=row.samples_upserted,
        samples_skipped=row.samples_skipped,
        samples_failed=row.samples_failed,
    )


def _scan_warnings(session: Session, scan_run_id: str) -> list[SampleWarningsGroup]:
    """Warnings for a single scan run, grouped by sample (sorted by sample id)."""
    rows = session.execute(
        select(orm.ScanWarningsORM.sample_id, orm.ScanWarningsORM.message)
        .where(orm.ScanWarningsORM.scan_run_id == scan_run_id)
        .order_by(orm.ScanWarningsORM.sample_id, orm.ScanWarningsORM.id)
    ).all()

    grouped: dict[str, list[str]] = {}
    for sample_id, message in rows:
        grouped.setdefault(sample_id, []).append(message)
    return [
        SampleWarningsGroup(sample_id=sid, warnings=msgs)
        for sid, msgs in grouped.items()
    ]


def _run_warnings(session: Session, scan_run_id: str) -> list[RunWarningOut]:
    """Run-level (no-sample) warnings for a single scan run, ordered by id."""
    rows = session.execute(
        select(orm.ScanRunWarningsORM)
        .where(orm.ScanRunWarningsORM.scan_run_id == scan_run_id)
        .order_by(orm.ScanRunWarningsORM.id)
    ).scalars().all()
    return [
        RunWarningOut(
            id=r.id, category=r.category, location=r.location,
            message=r.message, detected_at=r.detected_at,
            scan_run_id=r.scan_run_id,
        )
        for r in rows
    ]


def _scan_samples(
    session: Session, scan_run_id: str, outcome: Outcome
) -> list[ScanSampleOut]:
    """Samples with the given outcome in a single scan run.

    Sample metadata (data_source/project/type) is joined from ``samples`` when
    the row still exists; failed samples that were never persisted come back
    with null metadata and an error ``detail``.
    """
    # Per-sample warning count for the same scan, so the table can show it.
    warn_count_sq = (
        select(
            orm.ScanWarningsORM.sample_id.label("sample_id"),
            func.count().label("wc"),
        )
        .where(orm.ScanWarningsORM.scan_run_id == scan_run_id)
        .group_by(orm.ScanWarningsORM.sample_id)
        .subquery()
    )

    rows = session.execute(
        select(
            orm.ScanSamplesORM.sample_id,
            orm.ScanSamplesORM.detail,
            orm.SampleORM.data_source,
            orm.SampleORM.project,
            orm.SampleORM.type,
            func.coalesce(warn_count_sq.c.wc, 0),
        )
        .outerjoin(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.ScanSamplesORM.sample_id,
        )
        .outerjoin(
            warn_count_sq,
            warn_count_sq.c.sample_id == orm.ScanSamplesORM.sample_id,
        )
        .where(orm.ScanSamplesORM.scan_run_id == scan_run_id)
        .where(orm.ScanSamplesORM.outcome == outcome)
        .order_by(orm.ScanSamplesORM.sample_id)
    ).all()

    return [
        ScanSampleOut(
            sample_id=r[0],
            detail=r[1],
            data_source=_enum_val(r[2]),
            project=_enum_val(r[3]),
            type=r[4],
            warning_count=r[5],
        )
        for r in rows
    ]


@router.get("", response_model=list[ScanOut])
def list_scans(session: Session = Depends(get_session)):
    rows = session.execute(
        select(orm.ScansORM).order_by(orm.ScansORM.started_at.desc())
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/latest", response_model=ScanOut)
def get_latest_completed(session: Session = Depends(get_session)):
    row = session.execute(
        select(orm.ScansORM)
        .where(orm.ScansORM.status == "completed")
        .order_by(orm.ScansORM.ended_at.desc())
        .limit(1)
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="no completed scan")
    return _to_out(row)


@router.get("/latest/warnings", response_model=list[SampleWarningsGroup])
def get_latest_scan_warnings(session: Session = Depends(get_session)):
    """Warnings from the latest completed scan, grouped by sample.

    Returns an empty list when no completed scan exists yet (mirrors the
    per-sample ``/samples/{id}/warnings`` empty-on-no-scan behavior).
    """
    latest = _latest_completed_scan_id(session)
    if latest is None:
        return []
    return _scan_warnings(session, latest)


@router.get("/latest/run-warnings", response_model=list[RunWarningOut])
def get_latest_run_warnings(session: Session = Depends(get_session)):
    """Run-level warnings from the latest completed scan (empty if none)."""
    latest = _latest_completed_scan_id(session)
    if latest is None:
        return []
    return _run_warnings(session, latest)


@router.get("/latest/samples", response_model=list[ScanSampleOut])
def get_latest_scan_samples(
    outcome: Outcome = Query(...),
    session: Session = Depends(get_session),
):
    """Samples with the given outcome in the latest completed scan.

    Empty list when no completed scan exists.
    """
    latest = _latest_completed_scan_id(session)
    if latest is None:
        return []
    return _scan_samples(session, latest, outcome)


# NOTE: the ``/{scan_run_id}`` routes must be declared after every literal
# ``/latest`` path — FastAPI matches routes in registration order, and a bare
# path-param route would otherwise swallow the literal ``/latest`` segment.
@router.get("/{scan_run_id}", response_model=ScanOut)
def get_scan(scan_run_id: str, session: Session = Depends(get_session)):
    row = session.get(orm.ScansORM, scan_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _to_out(row)


@router.get("/{scan_run_id}/warnings", response_model=list[SampleWarningsGroup])
def get_scan_warnings(scan_run_id: str, session: Session = Depends(get_session)):
    """Warnings for a specific scan run, grouped by sample. 404 if unknown."""
    if session.get(orm.ScansORM, scan_run_id) is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _scan_warnings(session, scan_run_id)


@router.get("/{scan_run_id}/run-warnings", response_model=list[RunWarningOut])
def get_run_warnings(scan_run_id: str, session: Session = Depends(get_session)):
    """Run-level warnings for a specific scan run. 404 if unknown."""
    if session.get(orm.ScansORM, scan_run_id) is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _run_warnings(session, scan_run_id)


@router.get("/{scan_run_id}/samples", response_model=list[ScanSampleOut])
def get_scan_samples(
    scan_run_id: str,
    outcome: Outcome = Query(...),
    session: Session = Depends(get_session),
):
    """Samples with the given outcome in a specific scan run. 404 if unknown."""
    if session.get(orm.ScansORM, scan_run_id) is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _scan_samples(session, scan_run_id, outcome)
