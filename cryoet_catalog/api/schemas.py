"""Pydantic response models for the API.

Separate from cryoet_schema models — these are flat, JSON-consumer-shaped output
types so the API can evolve its response shape without touching the validation
schema. Frontend ``frontend/src/api/types.ts`` mirrors these field-by-field.
"""
from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel


# ── Sample list / summary ────────────────────────────────────────────────


class SampleSummary(BaseModel):
    sample_id: str
    project: str
    data_source: str
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    path: str | None = None
    warning_count: int = 0
    # Total child-row counts intrinsic to the sample — filter-independent.
    # ``n_tomograms`` is summed across raw + post-processed tables.
    n_acquisitions: int = 0
    n_tomograms: int = 0
    n_tilt_series: int = 0


# ── Sample detail: typed sub-entities ────────────────────────────────────


class ChromatinOut(BaseModel):
    substrate: str | None = None
    linker_length_bp: float | None = None
    linker_pattern: list[int] | None = None
    linker_distribution: str | None = None
    buffer: str | None = None
    ptm: str | None = None
    histone_variants: str | None = None
    transcription_factors: str | None = None
    nucleosome_count: int | None = None
    dna_length_bp: int | None = None
    nucleosome_uM: float | None = None
    sequence_identity: str | None = None
    nucleosome_footprint: list[int] | None = None
    linker_length_fraction: float | None = None


class LabelOut(BaseModel):
    ordinal: int
    label_target: str | None = None
    aunp_type: str | None = None
    # Polymorphic in the schema (single nanogold size or a list of sizes).
    aunp_size_nm: float | list[float] | None = None
    conjugation: str | None = None
    conjugation_target: str | None = None
    fluorophore: str | None = None
    notes: str | None = None


class FiducialOut(BaseModel):
    aunp_size_nm: float | None = None
    vendor: str | None = None
    catalog_number: str | None = None
    product_name: str | None = None
    concentration_value: float | None = None
    concentration_unit: str | None = None


class SimulationOut(BaseModel):
    dataset_type: str | None = None


class FreezingOut(BaseModel):
    grid_type: str | None = None
    solution_type: str | None = None
    cryoprotectant: str | None = None
    method: str | None = None
    planchette_size: str | None = None
    spacer_thickness: str | None = None


class MillingOut(BaseModel):
    scheme: str | None = None
    date: _dt.date | None = None
    quality: str | None = None


class MdRunOut(BaseModel):
    md_run_id: str
    seed: int | None = None
    computer: str | None = None


class _TomogramOutBase(BaseModel):
    """Fields shared by raw and post-processed tomogram outputs.

    Kept in one base class so the frontend can render both kinds with
    shared cell logic.
    """

    tomogram_id: str
    voxel_size: float | None = None                  # angstrom
    derived_from: list[str] = []
    image_size_x: int | None = None
    image_size_y: int | None = None
    image_size_z: int | None = None
    mrc_path: str | None = None
    zarr_path: str | None = None
    zarr_axes: str | None = None
    zarr_scale: list[float] | None = None


class RawTomogramOut(_TomogramOutBase):
    pipeline: str | None = None
    software: str | None = None


class PostProcessedTomogramOut(_TomogramOutBase):
    denoising_software: str | None = None
    ctf_software: str | None = None
    missing_wedge_software: str | None = None
    size_bytes: int | None = None


class AnnotationOut(BaseModel):
    annotation_id: str
    type: str | None = None
    target_tomogram: str | None = None
    files: list[str] = []


class TiltSeriesOut(BaseModel):
    tilt_series_id: str
    mdoc_path: str | None = None
    st_path: str | None = None
    zarr_path: str | None = None
    n_tilts: int | None = None
    tilt_range_min: float | None = None
    tilt_range_max: float | None = None
    tilt_axis_angle: float | None = None
    voltage: float | None = None
    pixel_spacing: float | None = None
    image_format: str | None = None
    microscope: str | None = None
    camera: str | None = None


class MdSourceOut(BaseModel):
    md_run_id: str | None = None
    frame: int | None = None


class AcquisitionOut(BaseModel):
    acquisition_id: str
    resolution: float | None = None
    microscope: str | None = None
    quality: str | None = None
    pixel_size: float | None = None
    voltage: float | None = None
    camera: str | None = None
    path: str | None = None
    md_source: MdSourceOut | None = None
    raw_tomogram: RawTomogramOut | None = None
    post_processed_tomograms: list[PostProcessedTomogramOut] = []
    annotations: list[AnnotationOut] = []
    tilt_series: list[TiltSeriesOut] = []


class SampleDetail(BaseModel):
    sample_id: str
    project: str
    data_source: str
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    path: str | None = None
    chromatin: ChromatinOut | None = None
    fiducial: FiducialOut | None = None
    simulation: SimulationOut | None = None
    freezing: FreezingOut | None = None
    milling: MillingOut | None = None
    label: list[LabelOut] = []
    md_run: list[MdRunOut] = []
    acquisitions: list[AcquisitionOut] = []


# ── Filters / stats / viewers ────────────────────────────────────────────


class RangeOut(BaseModel):
    """Range bounds; ``None`` when no rows exist for the facet."""
    min: float | None = None
    max: float | None = None


class FiltersOptionsOut(BaseModel):
    projects: list[str] = []
    data_sources: list[str] = []
    types: list[str] = []
    microscopes: list[str] = []
    voltages: list[float] = []
    cameras: list[str] = []
    image_formats: list[str] = []
    pixel_size: RangeOut = RangeOut()
    voxel_size: RangeOut = RangeOut()
    n_tilts: RangeOut = RangeOut()


class StatsTotalsOut(BaseModel):
    samples: int = 0
    acquisitions: int = 0
    tilt_series: int = 0
    # Sum across raw + post-processed tomogram tables.
    tomograms: int = 0
    annotations: int = 0
    warnings: int = 0


class ProjectStatRow(BaseModel):
    project: str
    samples: int = 0
    acquisitions: int = 0
    # Sum across raw + post-processed tomogram tables.
    tomograms: int = 0
    # Sum across PostProcessedTomogramORM.size_bytes only — RawTomogram has
    # no size_bytes field in the schema.
    size_bytes: int = 0


class StatsOverviewOut(BaseModel):
    totals: StatsTotalsOut
    by_project: list[ProjectStatRow] = []


class ViewerLaunchOut(BaseModel):
    """Response of a POST .../neuroglancer launch.

    Frontend rewrites the hostname to ``window.location.hostname`` before
    opening.
    """
    url: str


# ── Scan history / warnings / extras ─────────────────────────────────────


class WarningOut(BaseModel):
    id: int
    sample_id: str
    category: str
    location: str
    message: str
    detected_at: float
    scan_run_id: str


class ScanOut(BaseModel):
    scan_run_id: str
    started_at: float
    ended_at: float | None = None
    root: str
    status: str
    samples_upserted: int | None = None
    samples_skipped: int | None = None
    samples_failed: int | None = None


class ExtrasSummaryRow(BaseModel):
    entity_type: str
    key: str
    count: int
