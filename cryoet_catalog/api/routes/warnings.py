"""GET /samples/{sample_id}/warnings."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cryoet_catalog import orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.schemas import WarningOut

router = APIRouter()


@router.get("/{sample_id}/warnings", response_model=list[WarningOut])
def get_sample_warnings(sample_id: str, session: Session = Depends(get_session)):
    """Warnings from the most recent completed scan for this sample."""
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")

    # Find the most recent completed scan
    latest = session.execute(
        select(orm.ScansORM.scan_run_id)
        .where(orm.ScansORM.status == "completed")
        .order_by(orm.ScansORM.ended_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return []

    rows = session.execute(
        select(orm.ScanWarningsORM)
        .where(orm.ScanWarningsORM.sample_id == sample_id)
        .where(orm.ScanWarningsORM.scan_run_id == latest)
        .order_by(orm.ScanWarningsORM.id)
    ).scalars().all()
    return [WarningOut(
        id=r.id, sample_id=r.sample_id, category=r.category,
        location=r.location, message=r.message,
        detected_at=r.detected_at, scan_run_id=r.scan_run_id,
    ) for r in rows]
