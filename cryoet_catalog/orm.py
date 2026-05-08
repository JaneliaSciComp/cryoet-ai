"""SQLAlchemy 2.0 declarative ORM mirroring ``cryoet_schema.schema``.

Every Pydantic class in :mod:`cryoet_schema.schema` has a corresponding ORM
class here. The mapping is pinned by ``tests/cryoet_catalog/test_orm_drift.py``;
adding a Pydantic field requires adding a column here, and vice versa (modulo
the explicit DB-only carve-outs in the drift test).
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cryoet_schema.schema import _ID_MAX_LEN, DataSource, Project


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Sample + per-sample sub-tables
# ---------------------------------------------------------------------------


class SampleORM(Base):
    __tablename__ = "samples"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), primary_key=True)
    data_source: Mapped[DataSource] = mapped_column(SAEnum(DataSource), nullable=False)
    project: Mapped[Project] = mapped_column(SAEnum(Project), nullable=False)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    cell_type: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # DB-only: soft-delete timestamp
    deleted_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class ChromatinORM(Base):
    __tablename__ = "chromatin"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    substrate: Mapped[str | None] = mapped_column(String, nullable=True)
    linker_length_bp: Mapped[float | None] = mapped_column(Float, nullable=True)
    linker_pattern: Mapped[list | None] = mapped_column(JSON, nullable=True)
    linker_distribution: Mapped[str | None] = mapped_column(String, nullable=True)
    buffer: Mapped[str | None] = mapped_column(String, nullable=True)
    ptm: Mapped[str | None] = mapped_column(String, nullable=True)
    histone_variants: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_factors: Mapped[str | None] = mapped_column(String, nullable=True)
    nucleosome_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dna_length_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nucleosome_uM: Mapped[float | None] = mapped_column(Float, nullable=True)
    sequence_identity: Mapped[str | None] = mapped_column(String, nullable=True)
    nucleosome_footprint: Mapped[list | None] = mapped_column(JSON, nullable=True)
    linker_length_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)


class SynapseORM(Base):
    __tablename__ = "synapse"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    label_target: Mapped[str | None] = mapped_column(String, nullable=True)
    label_strategy: Mapped[str | None] = mapped_column(String, nullable=True)


class SimulationORM(Base):
    __tablename__ = "simulation"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    dataset_type: Mapped[str | None] = mapped_column(String, nullable=True)


class FreezingORM(Base):
    __tablename__ = "freezing"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    grid_type: Mapped[str | None] = mapped_column(String, nullable=True)
    cryoprotectant: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str | None] = mapped_column(String, nullable=True)
    planchette_size: Mapped[str | None] = mapped_column(String, nullable=True)
    spacer_thickness: Mapped[str | None] = mapped_column(String, nullable=True)


class MillingORM(Base):
    __tablename__ = "milling"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        primary_key=True,
    )
    scheme: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)


class AunpORM(Base):
    __tablename__ = "aunp"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    size_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    fluorophore: Mapped[str | None] = mapped_column(String, nullable=True)
    concentration_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    conjugation: Mapped[str | None] = mapped_column(String, nullable=True)
    conjugation_target: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("sample_id", "ordinal"),)


# ---------------------------------------------------------------------------
# Acquisition + tomogram + annotation
# ---------------------------------------------------------------------------


class AcquisitionORM(Base):
    __tablename__ = "acquisitions"

    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
    )
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    resolution: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_spacing: Mapped[float | None] = mapped_column(Float, nullable=True)
    defocus_range: Mapped[str | None] = mapped_column(String, nullable=True)
    energy_filter: Mapped[str | None] = mapped_column(String, nullable=True)
    phase_plate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    microscope: Mapped[str | None] = mapped_column(String, nullable=True)
    pixel_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    dose_per_tilt: Mapped[list | None] = mapped_column(JSON, nullable=True)
    total_dose: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_axis: Mapped[float | None] = mapped_column(Float, nullable=True)
    defocus_per_image: Mapped[list | None] = mapped_column(JSON, nullable=True)
    date_collected: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_filter_slit_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("sample_id", "acquisition_id"),)


class TomogramORM(Base):
    __tablename__ = "tomograms"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    tomogram_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    pipeline: Mapped[str | None] = mapped_column(String, nullable=True)
    software: Mapped[str | None] = mapped_column(String, nullable=True)
    voxel_bin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    derived_from: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_raw: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    image_size_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_size_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_size_z: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mrc_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_path: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_axes: Mapped[str | None] = mapped_column(String, nullable=True)
    zarr_scale: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # DB-only — populated by catalog scanner from MRC header / OME-Zarr scale
    voxel_spacing_angstrom: Mapped[float | None] = mapped_column(Float, nullable=True)
    voxel_spacing_angstrom_implied: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id", "tomogram_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


class AnnotationORM(Base):
    __tablename__ = "annotations"

    sample_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    annotation_id: Mapped[str] = mapped_column(String(_ID_MAX_LEN), nullable=False)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_tomogram: Mapped[str | None] = mapped_column(
        String(_ID_MAX_LEN), nullable=True
    )
    files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        PrimaryKeyConstraint("sample_id", "acquisition_id", "annotation_id"),
        ForeignKeyConstraint(
            ["sample_id", "acquisition_id"],
            ["acquisitions.sample_id", "acquisitions.acquisition_id"],
        ),
    )


# ---------------------------------------------------------------------------
# Housekeeping tables (no Pydantic counterpart)
# ---------------------------------------------------------------------------


class ExtrasORM(Base):
    __tablename__ = "extras"

    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_pk_json: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
        index=True,
    )
    value_json: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("entity_type", "entity_pk_json", "key"),
    )


class ScansORM(Base):
    __tablename__ = "scans"

    scan_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[float] = mapped_column(Float, nullable=False)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    root: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    samples_upserted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    samples_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    samples_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ScanWarningsORM(Base):
    __tablename__ = "scan_warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    detected_at: Mapped[float] = mapped_column(Float, nullable=False)
    scan_run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("scans.scan_run_id"),
        nullable=False,
        index=True,
    )


class ScanStateORM(Base):
    __tablename__ = "scan_state"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        String(_ID_MAX_LEN),
        ForeignKey("samples.sample_id"),
        nullable=False,
        index=True,
    )
    mtime: Mapped[float] = mapped_column(Float, nullable=False)
    last_scanned: Mapped[float] = mapped_column(Float, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class CatalogMetaORM(Base):
    __tablename__ = "catalog_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_root: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (CheckConstraint("id = 1", name="catalog_meta_singleton"),)
