"""GET /samples and /samples/{sample_id}."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from cryoet_catalog import orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.schemas import (
    SampleSummary, SampleDetail, AcquisitionOut, TomogramOut, AnnotationOut, AunpOut,
)

router = APIRouter()


def _to_summary(row: orm.SampleORM, warning_count: int) -> SampleSummary:
    return SampleSummary(
        sample_id=row.sample_id,
        project=row.project.value if hasattr(row.project, "value") else row.project,
        data_source=row.data_source.value if hasattr(row.data_source, "value") else row.data_source,
        type=row.type, cell_type=row.cell_type, description=row.description,
        warning_count=warning_count,
    )


@router.get("", response_model=list[SampleSummary])
def list_samples(
    project: str | None = Query(None),
    data_source: str | None = Query(None),
    has_warnings: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Paginated list of live samples (deleted_at IS NULL)."""
    # Subquery: warning count per sample
    warn_count_sq = (
        select(orm.ScanWarningsORM.sample_id, func.count(orm.ScanWarningsORM.id).label("wc"))
        .group_by(orm.ScanWarningsORM.sample_id)
        .subquery()
    )
    stmt = (
        select(orm.SampleORM, func.coalesce(warn_count_sq.c.wc, 0))
        .outerjoin(warn_count_sq, warn_count_sq.c.sample_id == orm.SampleORM.sample_id)
        .where(orm.SampleORM.deleted_at.is_(None))
    )
    if project:
        stmt = stmt.where(orm.SampleORM.project == project)
    if data_source:
        stmt = stmt.where(orm.SampleORM.data_source == data_source)
    if has_warnings is True:
        stmt = stmt.where(func.coalesce(warn_count_sq.c.wc, 0) > 0)
    elif has_warnings is False:
        stmt = stmt.where(func.coalesce(warn_count_sq.c.wc, 0) == 0)
    stmt = stmt.order_by(orm.SampleORM.sample_id).limit(limit).offset(offset)

    rows = session.execute(stmt).all()
    return [_to_summary(r[0], r[1]) for r in rows]


def _model_to_dict(row) -> dict:
    """Generic ORM row → dict of column values, dropping None and the sample_id FK."""
    d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    d.pop("sample_id", None)
    # Coerce enums to .value if they are
    for k, v in list(d.items()):
        if hasattr(v, "value") and hasattr(type(v), "_value2member_map_"):
            d[k] = v.value
    return d


@router.get("/{sample_id}", response_model=SampleDetail)
def get_sample(sample_id: str, session: Session = Depends(get_session)):
    """Full sample record with sub-entities and acquisitions. 404 for missing or soft-deleted."""
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")

    sub = {}
    for attr_name, sub_orm in [
        ("chromatin", orm.ChromatinORM),
        ("synapse", orm.SynapseORM),
        ("simulation", orm.SimulationORM),
        ("freezing", orm.FreezingORM),
        ("milling", orm.MillingORM),
    ]:
        row = session.get(sub_orm, sample_id)
        sub[attr_name] = _model_to_dict(row) if row else None

    aunp_rows = session.execute(
        select(orm.AunpORM).where(orm.AunpORM.sample_id == sample_id).order_by(orm.AunpORM.ordinal)
    ).scalars().all()
    aunp_out = [AunpOut(**{c.name: getattr(a, c.name) for c in a.__table__.columns if c.name != "sample_id"}) for a in aunp_rows]

    # Acquisitions + tomograms + annotations
    acqs = session.execute(
        select(orm.AcquisitionORM).where(orm.AcquisitionORM.sample_id == sample_id).order_by(orm.AcquisitionORM.acquisition_id)
    ).scalars().all()
    acq_out = []
    for a in acqs:
        tomos = session.execute(
            select(orm.TomogramORM)
            .where(orm.TomogramORM.sample_id == sample_id)
            .where(orm.TomogramORM.acquisition_id == a.acquisition_id)
            .order_by(orm.TomogramORM.tomogram_id)
        ).scalars().all()
        anns = session.execute(
            select(orm.AnnotationORM)
            .where(orm.AnnotationORM.sample_id == sample_id)
            .where(orm.AnnotationORM.acquisition_id == a.acquisition_id)
            .order_by(orm.AnnotationORM.annotation_id)
        ).scalars().all()
        acq_out.append(AcquisitionOut(
            acquisition_id=a.acquisition_id,
            resolution=a.resolution, microscope=a.microscope,
            pixel_size=a.pixel_size, voltage=a.voltage, camera=a.camera,
            tomograms=[TomogramOut(
                tomogram_id=t.tomogram_id, pipeline=t.pipeline, software=t.software,
                voxel_bin=t.voxel_bin,
                voxel_spacing_angstrom=t.voxel_spacing_angstrom,
                voxel_spacing_angstrom_implied=t.voxel_spacing_angstrom_implied,
                derived_from=t.derived_from or [], is_raw=t.is_raw,
                image_size_x=t.image_size_x, image_size_y=t.image_size_y, image_size_z=t.image_size_z,
                mrc_path=t.mrc_path, zarr_path=t.zarr_path,
                zarr_axes=t.zarr_axes, zarr_scale=t.zarr_scale,
            ) for t in tomos],
            annotations=[AnnotationOut(
                annotation_id=ann.annotation_id, type=ann.type,
                target_tomogram=ann.target_tomogram, files=ann.files or [],
            ) for ann in anns],
        ))

    return SampleDetail(
        sample_id=sample.sample_id,
        project=sample.project.value if hasattr(sample.project, "value") else sample.project,
        data_source=sample.data_source.value if hasattr(sample.data_source, "value") else sample.data_source,
        type=sample.type, cell_type=sample.cell_type, description=sample.description,
        chromatin=sub["chromatin"], synapse=sub["synapse"], simulation=sub["simulation"],
        freezing=sub["freezing"], milling=sub["milling"],
        aunp=aunp_out, acquisitions=acq_out,
    )
