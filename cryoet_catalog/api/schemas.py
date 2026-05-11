"""Pydantic response models for the API.

Separate from cryoet_schema models — these are flat, JSON-consumer-shaped output
types so the API can evolve its response shape without touching the validation
schema. Frontend ``frontend/src/api/types.ts`` mirrors these field-by-field
(decision §11.18: typed Pydantic per sub-entity, no ``dict[str, Any]`` on the
wire).
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
    warning_count: int = 0
    # Total child-row counts intrinsic to the sample — filter-independent
    # (decision §11.15). Correlated subqueries on the SELECT list.
    n_acquisitions: int = 0
    n_tomograms: int = 0
    n_tilt_series: int = 0


# ── Sample detail: typed sub-entities (decision §11.18) ──────────────────


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


class SynapseOut(BaseModel):
    label_target: str | None = None
    label_strategy: str | None = None


class SimulationOut(BaseModel):
    # Matches the existing ``Simulation`` Pydantic model — no MD-specific
    # fields are added in this MVP (§14).
    dataset_type: str | None = None


class FreezingOut(BaseModel):
    grid_type: str | None = None
    cryoprotectant: str | None = None
    method: str | None = None
    planchette_size: str | None = None
    spacer_thickness: str | None = None


class MillingOut(BaseModel):
    scheme: str | None = None
    date: _dt.date | None = None


class AunpOut(BaseModel):
    ordinal: int
    size_nm: float | None = None
    type: str | None = None
    fluorophore: str | None = None
    concentration_value: float | None = None
    concentration_unit: str | None = None
    conjugation: str | None = None
    conjugation_target: str | None = None
    notes: str | None = None


class TomogramOut(BaseModel):
    tomogram_id: str
    pipeline: str | None = None
    software: str | None = None
    voxel_bin: int | None = None
    voxel_spacing_angstrom: float | None = None       # MRC-header derived
    voxel_spacing_angstrom_implied: float | None = None
    derived_from: list[str] = []
    is_raw: bool | None = None
    image_size_x: int | None = None
    image_size_y: int | None = None
    image_size_z: int | None = None
    mrc_path: str | None = None
    zarr_path: str | None = None
    zarr_axes: str | None = None
    zarr_scale: list[float] | None = None
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


class AcquisitionOut(BaseModel):
    acquisition_id: str
    resolution: float | None = None
    microscope: str | None = None
    pixel_size: float | None = None
    voltage: float | None = None
    camera: str | None = None
    path: str | None = None
    tomograms: list[TomogramOut] = []
    annotations: list[AnnotationOut] = []
    tilt_series: list[TiltSeriesOut] = []


class SampleDetail(BaseModel):
    sample_id: str
    project: str
    data_source: str
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    chromatin: ChromatinOut | None = None
    synapse: SynapseOut | None = None
    simulation: SimulationOut | None = None
    freezing: FreezingOut | None = None
    milling: MillingOut | None = None
    aunp: list[AunpOut] = []
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
    voxel_spacing: RangeOut = RangeOut()
    n_tilts: RangeOut = RangeOut()


class StatsTotalsOut(BaseModel):
    samples: int = 0
    acquisitions: int = 0
    tilt_series: int = 0
    tomograms: int = 0
    annotations: int = 0
    warnings: int = 0


class ProjectStatRow(BaseModel):
    project: str
    samples: int = 0
    acquisitions: int = 0
    tomograms: int = 0
    size_bytes: int = 0


class StatsOverviewOut(BaseModel):
    totals: StatsTotalsOut
    by_project: list[ProjectStatRow] = []


class ViewerLaunchOut(BaseModel):
    """Response of a POST .../neuroglancer launch.

    Frontend rewrites the hostname to ``window.location.hostname`` before
    opening (matches ``aicryoet-tools/.../pages/cryoet.py:1166``).
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
