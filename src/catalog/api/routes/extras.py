"""GET /extras/summary."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.schemas import ExtrasSummaryRow

router = APIRouter()


@router.get("/summary", response_model=list[ExtrasSummaryRow])
def extras_summary(session: Session = Depends(get_session)):
    """Group extras rows by (entity_type, key), most common first."""
    rows = session.execute(
        select(
            orm.ExtrasORM.entity_type, orm.ExtrasORM.key,
            func.count(orm.ExtrasORM.entity_pk_json).label("cnt"),
        )
        .group_by(orm.ExtrasORM.entity_type, orm.ExtrasORM.key)
        .order_by(func.count(orm.ExtrasORM.entity_pk_json).desc())
    ).all()
    return [ExtrasSummaryRow(entity_type=r[0], key=r[1], count=r[2]) for r in rows]
