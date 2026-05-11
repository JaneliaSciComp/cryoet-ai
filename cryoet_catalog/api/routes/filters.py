"""GET /filters/options — categorical option lists and numeric ranges for the
sample filter drawer. Plan §7.2.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cryoet_catalog import orm
from cryoet_catalog.api.deps import get_session
from cryoet_catalog.api.schemas import FiltersOptionsOut, RangeOut

router = APIRouter()


def _enum_value(v):
    """Coerce a SQLAlchemy Enum value to its string (.value) form."""
    return v.value if hasattr(v, "value") else v


@router.get("/options", response_model=FiltersOptionsOut)
def get_filter_options(session: Session = Depends(get_session)):
    """Return distinct values + numeric ranges for the sample filter drawer.

    All queries are scoped to live samples (``samples.deleted_at IS NULL``);
    soft-deleted samples never contribute to options or range bounds.
    """
    # ── Categorical: samples.project / data_source / type ──────────────────
    project_rows = session.execute(
        select(orm.SampleORM.project)
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.SampleORM.project.is_not(None))
        .distinct()
        .order_by(orm.SampleORM.project)
    ).scalars().all()
    projects = sorted({_enum_value(p) for p in project_rows})

    data_source_rows = session.execute(
        select(orm.SampleORM.data_source)
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.SampleORM.data_source.is_not(None))
        .distinct()
        .order_by(orm.SampleORM.data_source)
    ).scalars().all()
    data_sources = sorted({_enum_value(d) for d in data_source_rows})

    types = list(session.execute(
        select(orm.SampleORM.type)
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.SampleORM.type.is_not(None))
        .distinct()
        .order_by(orm.SampleORM.type)
    ).scalars().all())

    # ── Categorical: acquisitions.microscope / voltage / camera ────────────
    # Join through samples so soft-deleted samples are excluded.
    microscopes = list(session.execute(
        select(orm.AcquisitionORM.microscope)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.AcquisitionORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.AcquisitionORM.microscope.is_not(None))
        .distinct()
        .order_by(orm.AcquisitionORM.microscope)
    ).scalars().all())

    voltages = list(session.execute(
        select(orm.AcquisitionORM.voltage)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.AcquisitionORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.AcquisitionORM.voltage.is_not(None))
        .distinct()
        .order_by(orm.AcquisitionORM.voltage)
    ).scalars().all())

    cameras = list(session.execute(
        select(orm.AcquisitionORM.camera)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.AcquisitionORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.AcquisitionORM.camera.is_not(None))
        .distinct()
        .order_by(orm.AcquisitionORM.camera)
    ).scalars().all())

    # ── Categorical: tilt_series.image_format ──────────────────────────────
    image_formats = list(session.execute(
        select(orm.TiltSeriesORM.image_format)
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.TiltSeriesORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.TiltSeriesORM.image_format.is_not(None))
        .distinct()
        .order_by(orm.TiltSeriesORM.image_format)
    ).scalars().all())

    # ── Numeric ranges ─────────────────────────────────────────────────────
    pixel_size_row = session.execute(
        select(
            func.min(orm.AcquisitionORM.pixel_size),
            func.max(orm.AcquisitionORM.pixel_size),
        )
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.AcquisitionORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.AcquisitionORM.pixel_size.is_not(None))
    ).one()
    pixel_size = RangeOut(min=pixel_size_row[0], max=pixel_size_row[1])

    voxel_spacing_row = session.execute(
        select(
            func.min(orm.TomogramORM.voxel_spacing_angstrom),
            func.max(orm.TomogramORM.voxel_spacing_angstrom),
        )
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.TomogramORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.TomogramORM.voxel_spacing_angstrom.is_not(None))
    ).one()
    voxel_spacing = RangeOut(
        min=voxel_spacing_row[0], max=voxel_spacing_row[1]
    )

    n_tilts_row = session.execute(
        select(
            func.min(orm.TiltSeriesORM.n_tilts),
            func.max(orm.TiltSeriesORM.n_tilts),
        )
        .join(
            orm.SampleORM,
            orm.SampleORM.sample_id == orm.TiltSeriesORM.sample_id,
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .where(orm.TiltSeriesORM.n_tilts.is_not(None))
    ).one()
    n_tilts = RangeOut(min=n_tilts_row[0], max=n_tilts_row[1])

    return FiltersOptionsOut(
        projects=projects,
        data_sources=data_sources,
        types=types,
        microscopes=microscopes,
        voltages=voltages,
        cameras=cameras,
        image_formats=image_formats,
        pixel_size=pixel_size,
        voxel_spacing=voxel_spacing,
        n_tilts=n_tilts,
    )
