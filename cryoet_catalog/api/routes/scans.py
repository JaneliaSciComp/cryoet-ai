"""GET /scans, /scans/latest, /scans/{scan_run_id}."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cryoet_catalog import orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.schemas import ScanOut

router = APIRouter()


def _to_out(row: orm.ScansORM) -> ScanOut:
    return ScanOut(
        scan_run_id=row.scan_run_id,
        started_at=row.started_at, ended_at=row.ended_at,
        root=row.root, status=row.status,
        samples_upserted=row.samples_upserted,
        samples_skipped=row.samples_skipped,
        samples_failed=row.samples_failed,
    )


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


# NOTE: must be declared after ``/latest`` — FastAPI matches routes in
# registration order, and a bare ``/{scan_run_id}`` would otherwise swallow
# the literal ``/latest`` path.
@router.get("/{scan_run_id}", response_model=ScanOut)
def get_scan(scan_run_id: str, session: Session = Depends(get_session)):
    row = session.get(orm.ScansORM, scan_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _to_out(row)
