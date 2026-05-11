"""GET /samples and /samples/{sample_id}."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from cryoet_catalog import orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.schemas import (
    AcquisitionOut,
    AnnotationOut,
    AunpOut,
    ChromatinOut,
    FreezingOut,
    MillingOut,
    SampleDetail,
    SampleSummary,
    SimulationOut,
    SynapseOut,
    TiltSeriesOut,
    TomogramOut,
)

router = APIRouter()


def _enum_val(v):
    """Coerce a possibly-enum value to its string value."""
    return v.value if hasattr(v, "value") else v


# Pydantic sub-entity schemas paired with their ORM sources. Each sub-entity
# table has ``sample_id`` as its PK so we can fetch via ``session.get``.
_SUB_ENTITY_MAP: tuple[tuple[str, type, type], ...] = (
    ("chromatin", orm.ChromatinORM, ChromatinOut),
    ("synapse", orm.SynapseORM, SynapseOut),
    ("simulation", orm.SimulationORM, SimulationOut),
    ("freezing", orm.FreezingORM, FreezingOut),
    ("milling", orm.MillingORM, MillingOut),
)


def _build_sub_entity(row, out_cls: type):
    """Construct an XxxOut Pydantic model from an ORM row, picking only the
    columns the Pydantic model declares (so DB-only columns like ``sample_id``
    don't leak in).
    """
    if row is None:
        return None
    field_names = out_cls.model_fields.keys()
    values = {name: getattr(row, name, None) for name in field_names}
    return out_cls(**values)


@router.get("", response_model=list[SampleSummary])
def list_samples(
    project: list[str] | None = Query(None),
    data_source: list[str] | None = Query(None),
    type: list[str] | None = Query(None),
    microscope: list[str] | None = Query(None),
    voltage: list[float] | None = Query(None),
    camera: list[str] | None = Query(None),
    pixel_size_min: float | None = Query(None),
    pixel_size_max: float | None = Query(None),
    voxel_spacing_min: float | None = Query(None),
    voxel_spacing_max: float | None = Query(None),
    n_tilts_min: int | None = Query(None),
    n_tilts_max: int | None = Query(None),
    image_format: list[str] | None = Query(None),
    has_tomograms: bool | None = Query(None),
    q: str | None = Query(None),
    has_warnings: bool | None = Query(None),
    sort: Literal["sample_id", "project", "type"] = Query("sample_id"),
    order: Literal["asc", "desc"] = Query("asc"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Paginated list of live samples (deleted_at IS NULL) with filters and
    intrinsic child-row counts (n_acquisitions/n_tomograms/n_tilt_series).

    Filter semantics (plan §7.1, decision §11.15):
      * Repeatable categorical params act as OR within a facet, AND across.
      * Acquisition/tomogram/tilt_series filters use EXISTS subqueries on the
        respective child table.
      * Range filters are NULL-tolerant: a child row with NULL on the bound
        column is treated as a match (so partial metadata doesn't drop the
        whole sample).
      * Counts on the SELECT list are filter-INDEPENDENT total child rows.
    """
    # ── Subqueries ────────────────────────────────────────────────────────
    # Warning count per sample.
    warn_count_sq = (
        select(
            orm.ScanWarningsORM.sample_id,
            func.count(orm.ScanWarningsORM.id).label("wc"),
        )
        .group_by(orm.ScanWarningsORM.sample_id)
        .subquery()
    )

    # Filter-independent total child counts (correlated subqueries).
    n_acq_sq = (
        select(func.count())
        .select_from(orm.AcquisitionORM)
        .where(orm.AcquisitionORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )
    n_tomo_sq = (
        select(func.count())
        .select_from(orm.TomogramORM)
        .where(orm.TomogramORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )
    n_ts_sq = (
        select(func.count())
        .select_from(orm.TiltSeriesORM)
        .where(orm.TiltSeriesORM.sample_id == orm.SampleORM.sample_id)
        .correlate(orm.SampleORM)
        .scalar_subquery()
    )

    stmt = (
        select(
            orm.SampleORM,
            func.coalesce(warn_count_sq.c.wc, 0).label("warning_count"),
            n_acq_sq.label("n_acquisitions"),
            n_tomo_sq.label("n_tomograms"),
            n_ts_sq.label("n_tilt_series"),
        )
        .outerjoin(warn_count_sq, warn_count_sq.c.sample_id == orm.SampleORM.sample_id)
        .where(orm.SampleORM.deleted_at.is_(None))
    )

    # ── Sample-table filters ──────────────────────────────────────────────
    if project:
        stmt = stmt.where(orm.SampleORM.project.in_(project))
    if data_source:
        stmt = stmt.where(orm.SampleORM.data_source.in_(data_source))
    if type:
        stmt = stmt.where(orm.SampleORM.type.in_(type))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(orm.SampleORM.sample_id).like(like),
                func.lower(orm.SampleORM.description).like(like),
            )
        )

    # ── Acquisition EXISTS filters ────────────────────────────────────────
    acq_conds = [orm.AcquisitionORM.sample_id == orm.SampleORM.sample_id]
    if microscope:
        acq_conds.append(orm.AcquisitionORM.microscope.in_(microscope))
    if voltage:
        acq_conds.append(orm.AcquisitionORM.voltage.in_(voltage))
    if camera:
        acq_conds.append(orm.AcquisitionORM.camera.in_(camera))
    if pixel_size_min is not None:
        acq_conds.append(
            or_(
                orm.AcquisitionORM.pixel_size.is_(None),
                orm.AcquisitionORM.pixel_size >= pixel_size_min,
            )
        )
    if pixel_size_max is not None:
        acq_conds.append(
            or_(
                orm.AcquisitionORM.pixel_size.is_(None),
                orm.AcquisitionORM.pixel_size <= pixel_size_max,
            )
        )
    if len(acq_conds) > 1:
        stmt = stmt.where(
            exists(select(1).where(and_(*acq_conds)).correlate(orm.SampleORM))
        )

    # ── Tomogram EXISTS filters ───────────────────────────────────────────
    tomo_conds = [orm.TomogramORM.sample_id == orm.SampleORM.sample_id]
    if voxel_spacing_min is not None:
        tomo_conds.append(
            or_(
                orm.TomogramORM.voxel_spacing_angstrom.is_(None),
                orm.TomogramORM.voxel_spacing_angstrom >= voxel_spacing_min,
            )
        )
    if voxel_spacing_max is not None:
        tomo_conds.append(
            or_(
                orm.TomogramORM.voxel_spacing_angstrom.is_(None),
                orm.TomogramORM.voxel_spacing_angstrom <= voxel_spacing_max,
            )
        )
    if len(tomo_conds) > 1:
        stmt = stmt.where(
            exists(select(1).where(and_(*tomo_conds)).correlate(orm.SampleORM))
        )

    if has_tomograms is True:
        stmt = stmt.where(
            exists(
                select(1)
                .where(orm.TomogramORM.sample_id == orm.SampleORM.sample_id)
                .correlate(orm.SampleORM)
            )
        )
    elif has_tomograms is False:
        stmt = stmt.where(
            ~exists(
                select(1)
                .where(orm.TomogramORM.sample_id == orm.SampleORM.sample_id)
                .correlate(orm.SampleORM)
            )
        )

    # ── Tilt-series EXISTS filters ────────────────────────────────────────
    ts_conds = [orm.TiltSeriesORM.sample_id == orm.SampleORM.sample_id]
    if n_tilts_min is not None:
        ts_conds.append(
            or_(
                orm.TiltSeriesORM.n_tilts.is_(None),
                orm.TiltSeriesORM.n_tilts >= n_tilts_min,
            )
        )
    if n_tilts_max is not None:
        ts_conds.append(
            or_(
                orm.TiltSeriesORM.n_tilts.is_(None),
                orm.TiltSeriesORM.n_tilts <= n_tilts_max,
            )
        )
    if image_format:
        ts_conds.append(orm.TiltSeriesORM.image_format.in_(image_format))
    if len(ts_conds) > 1:
        stmt = stmt.where(
            exists(select(1).where(and_(*ts_conds)).correlate(orm.SampleORM))
        )

    # ── Warnings filter ───────────────────────────────────────────────────
    if has_warnings is True:
        stmt = stmt.where(func.coalesce(warn_count_sq.c.wc, 0) > 0)
    elif has_warnings is False:
        stmt = stmt.where(func.coalesce(warn_count_sq.c.wc, 0) == 0)

    # ── Sort + pagination ─────────────────────────────────────────────────
    sort_col = {
        "sample_id": orm.SampleORM.sample_id,
        "project": orm.SampleORM.project,
        "type": orm.SampleORM.type,
    }[sort]
    stmt = stmt.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    # Stable tiebreaker so paged queries are deterministic when sorting on a
    # non-unique column.
    if sort != "sample_id":
        stmt = stmt.order_by(orm.SampleORM.sample_id.asc())
    stmt = stmt.limit(limit).offset(offset)

    rows = session.execute(stmt).all()
    return [
        SampleSummary(
            sample_id=r[0].sample_id,
            project=_enum_val(r[0].project),
            data_source=_enum_val(r[0].data_source),
            type=r[0].type,
            cell_type=r[0].cell_type,
            description=r[0].description,
            warning_count=r[1],
            n_acquisitions=r[2],
            n_tomograms=r[3],
            n_tilt_series=r[4],
        )
        for r in rows
    ]


@router.get("/{sample_id}", response_model=SampleDetail)
def get_sample(sample_id: str, session: Session = Depends(get_session)):
    """Full sample record with typed sub-entities, acquisitions, tomograms,
    annotations, and tilt_series. 404 for missing or soft-deleted.
    """
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")

    # Typed sub-entities (decision §11.18).
    sub: dict[str, object | None] = {}
    for attr_name, sub_orm, out_cls in _SUB_ENTITY_MAP:
        row = session.get(sub_orm, sample_id)
        sub[attr_name] = _build_sub_entity(row, out_cls)

    aunp_rows = (
        session.execute(
            select(orm.AunpORM)
            .where(orm.AunpORM.sample_id == sample_id)
            .order_by(orm.AunpORM.ordinal)
        )
        .scalars()
        .all()
    )
    aunp_field_names = AunpOut.model_fields.keys()
    aunp_out = [
        AunpOut(**{name: getattr(a, name, None) for name in aunp_field_names})
        for a in aunp_rows
    ]

    # Acquisitions + tomograms + annotations + tilt_series.
    acqs = (
        session.execute(
            select(orm.AcquisitionORM)
            .where(orm.AcquisitionORM.sample_id == sample_id)
            .order_by(orm.AcquisitionORM.acquisition_id)
        )
        .scalars()
        .all()
    )
    acq_out: list[AcquisitionOut] = []
    for a in acqs:
        tomos = (
            session.execute(
                select(orm.TomogramORM)
                .where(orm.TomogramORM.sample_id == sample_id)
                .where(orm.TomogramORM.acquisition_id == a.acquisition_id)
                .order_by(orm.TomogramORM.tomogram_id)
            )
            .scalars()
            .all()
        )
        anns = (
            session.execute(
                select(orm.AnnotationORM)
                .where(orm.AnnotationORM.sample_id == sample_id)
                .where(orm.AnnotationORM.acquisition_id == a.acquisition_id)
                .order_by(orm.AnnotationORM.annotation_id)
            )
            .scalars()
            .all()
        )
        ts_rows = (
            session.execute(
                select(orm.TiltSeriesORM)
                .where(orm.TiltSeriesORM.sample_id == sample_id)
                .where(orm.TiltSeriesORM.acquisition_id == a.acquisition_id)
                .order_by(orm.TiltSeriesORM.tilt_series_id)
            )
            .scalars()
            .all()
        )
        ts_field_names = TiltSeriesOut.model_fields.keys()
        acq_out.append(
            AcquisitionOut(
                acquisition_id=a.acquisition_id,
                resolution=a.resolution,
                microscope=a.microscope,
                pixel_size=a.pixel_size,
                voltage=a.voltage,
                camera=a.camera,
                path=a.path,
                tomograms=[
                    TomogramOut(
                        tomogram_id=t.tomogram_id,
                        pipeline=t.pipeline,
                        software=t.software,
                        voxel_bin=t.voxel_bin,
                        voxel_spacing_angstrom=t.voxel_spacing_angstrom,
                        voxel_spacing_angstrom_implied=t.voxel_spacing_angstrom_implied,
                        derived_from=t.derived_from or [],
                        is_raw=t.is_raw,
                        image_size_x=t.image_size_x,
                        image_size_y=t.image_size_y,
                        image_size_z=t.image_size_z,
                        mrc_path=t.mrc_path,
                        zarr_path=t.zarr_path,
                        zarr_axes=t.zarr_axes,
                        zarr_scale=t.zarr_scale,
                        size_bytes=t.size_bytes,
                    )
                    for t in tomos
                ],
                annotations=[
                    AnnotationOut(
                        annotation_id=ann.annotation_id,
                        type=ann.type,
                        target_tomogram=ann.target_tomogram,
                        files=ann.files or [],
                    )
                    for ann in anns
                ],
                tilt_series=[
                    TiltSeriesOut(
                        **{name: getattr(ts, name, None) for name in ts_field_names}
                    )
                    for ts in ts_rows
                ],
            )
        )

    return SampleDetail(
        sample_id=sample.sample_id,
        project=_enum_val(sample.project),
        data_source=_enum_val(sample.data_source),
        type=sample.type,
        cell_type=sample.cell_type,
        description=sample.description,
        chromatin=sub["chromatin"],
        synapse=sub["synapse"],
        simulation=sub["simulation"],
        freezing=sub["freezing"],
        milling=sub["milling"],
        aunp=aunp_out,
        acquisitions=acq_out,
    )
