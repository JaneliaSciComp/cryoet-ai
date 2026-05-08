"""Pydantic response models for the API.

Separate from cryoet_schema models — these are flat, JSON-consumer-shaped output
types so the API can evolve its response shape without touching the validation schema.
"""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class SampleSummary(BaseModel):
    sample_id: str
    project: str
    data_source: str
    type: str | None = None
    cell_type: str | None = None
    description: str | None = None
    warning_count: int = 0


class TomogramOut(BaseModel):
    tomogram_id: str
    pipeline: str | None
    software: str | None
    voxel_bin: int | None
    voxel_spacing_angstrom: float | None       # MRC-header derived
    voxel_spacing_angstrom_implied: float | None
    derived_from: list[str]
    is_raw: bool | None
    image_size_x: int | None
    image_size_y: int | None
    image_size_z: int | None
    mrc_path: str | None
    zarr_path: str | None
    zarr_axes: str | None
    zarr_scale: list[float] | None


class AnnotationOut(BaseModel):
    annotation_id: str
    type: str | None
    target_tomogram: str | None
    files: list[str]


class AcquisitionOut(BaseModel):
    acquisition_id: str
    resolution: float | None
    microscope: str | None
    pixel_size: float | None
    voltage: float | None
    camera: str | None
    tomograms: list[TomogramOut]
    annotations: list[AnnotationOut]


class SubEntity(BaseModel):
    """Polymorphic shape for chromatin/synapse/simulation/freezing/milling rows."""
    fields: dict[str, Any]


class AunpOut(BaseModel):
    ordinal: int
    size_nm: float | None
    type: str | None
    fluorophore: str | None
    concentration_value: float | None
    concentration_unit: str | None
    conjugation: str | None
    conjugation_target: str | None
    notes: str | None


class SampleDetail(BaseModel):
    sample_id: str
    project: str
    data_source: str
    type: str | None
    cell_type: str | None
    description: str | None
    chromatin: dict[str, Any] | None
    synapse: dict[str, Any] | None
    simulation: dict[str, Any] | None
    freezing: dict[str, Any] | None
    milling: dict[str, Any] | None
    aunp: list[AunpOut]
    acquisitions: list[AcquisitionOut]


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
    ended_at: float | None
    root: str
    status: str
    samples_upserted: int | None
    samples_skipped: int | None
    samples_failed: int | None


class ExtrasSummaryRow(BaseModel):
    entity_type: str
    key: str
    count: int
