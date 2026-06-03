"""GET /stats/overview — totals and per-project aggregates for the home page.
Plan §7.3.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cryoet_catalog import orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.schemas import (
    ProjectStatRow,
    StatsOverviewOut,
    StatsTotalsOut,
)

router = APIRouter()


def _enum_value(v):
    return v.value if hasattr(v, "value") else v


def _count_live(session: Session, child_orm) -> int:
    """Count rows in a child table whose parent sample is live."""
    return session.execute(
        select(func.count())
        .select_from(child_orm)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == child_orm.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
    ).scalar_one()


@router.get("/overview", response_model=StatsOverviewOut)
def get_stats_overview(session: Session = Depends(get_session)):
    """Aggregate totals + per-project rollup over live samples.

    ``totals.warnings`` reflects only the most recent completed scan
    (mirrors ``/samples/{id}/warnings`` semantics — Plan §7.3).
    """
    # ── Totals ─────────────────────────────────────────────────────────────
    samples_total = session.execute(
        select(func.count())
        .select_from(orm.SampleORM)
        .where(orm.SampleORM.deleted_at.is_(None))
    ).scalar_one()

    acquisitions_total = _count_live(session, orm.AcquisitionORM)
    tilt_series_total = _count_live(session, orm.TiltSeriesORM)
    # tomograms_total spans raw + post-processed tables.
    tomograms_total = (
        _count_live(session, orm.RawTomogramORM)
        + _count_live(session, orm.PostProcessedTomogramORM)
    )
    annotations_total = _count_live(session, orm.AnnotationORM)

    # Warnings: only count rows from the most recent completed scan.
    latest_scan = session.execute(
        select(orm.ScansORM.scan_run_id)
        .where(orm.ScansORM.status == "completed")
        .order_by(orm.ScansORM.ended_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_scan is None:
        warnings_total = 0
    else:
        warnings_total = session.execute(
            select(func.count())
            .select_from(orm.ScanWarningsORM)
            .where(orm.ScanWarningsORM.scan_run_id == latest_scan)
        ).scalar_one()

    totals = StatsTotalsOut(
        samples=samples_total,
        acquisitions=acquisitions_total,
        tilt_series=tilt_series_total,
        tomograms=tomograms_total,
        annotations=annotations_total,
        warnings=warnings_total,
    )

    # ── Per-project rollup ─────────────────────────────────────────────────
    # samples per project (live only)
    samples_by_project = dict(session.execute(
        select(orm.SampleORM.project, func.count(orm.SampleORM.sample_id))
        .where(orm.SampleORM.deleted_at.is_(None))
        .group_by(orm.SampleORM.project)
    ).all())

    # acquisitions per project (join samples to attribute project + filter live)
    acquisitions_by_project = dict(session.execute(
        select(
            orm.SampleORM.project,
            func.count(),
        )
        .select_from(orm.AcquisitionORM)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.AcquisitionORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .group_by(orm.SampleORM.project)
    ).all())

    # tomograms per project — sum of raw + post-processed.
    raw_tomos_by_project = dict(session.execute(
        select(
            orm.SampleORM.project,
            func.count(),
        )
        .select_from(orm.RawTomogramORM)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.RawTomogramORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .group_by(orm.SampleORM.project)
    ).all())
    post_tomos_by_project = dict(session.execute(
        select(
            orm.SampleORM.project,
            func.count(),
        )
        .select_from(orm.PostProcessedTomogramORM)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.PostProcessedTomogramORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .group_by(orm.SampleORM.project)
    ).all())
    tomograms_by_project: dict = {}
    for p in set(raw_tomos_by_project) | set(post_tomos_by_project):
        tomograms_by_project[p] = (
            raw_tomos_by_project.get(p, 0) + post_tomos_by_project.get(p, 0)
        )

    # size_bytes per project — only PostProcessedTomogram has size_bytes
    # (raw has no such field in the schema).
    size_by_project = dict(session.execute(
        select(
            orm.SampleORM.project,
            func.coalesce(func.sum(
                func.coalesce(orm.PostProcessedTomogramORM.size_bytes, 0)
            ), 0),
        )
        .select_from(orm.PostProcessedTomogramORM)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.PostProcessedTomogramORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .group_by(orm.SampleORM.project)
    ).all())

    # One row per project that has at least one live sample.
    projects_sorted = sorted(
        samples_by_project.keys(), key=lambda p: _enum_value(p)
    )
    by_project = [
        ProjectStatRow(
            project=_enum_value(p),
            samples=samples_by_project.get(p, 0),
            acquisitions=acquisitions_by_project.get(p, 0),
            tomograms=tomograms_by_project.get(p, 0),
            size_bytes=int(size_by_project.get(p, 0) or 0),
        )
        for p in projects_sorted
    ]

    return StatsOverviewOut(totals=totals, by_project=by_project)
