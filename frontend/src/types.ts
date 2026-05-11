// Hand-written mirror of cryoet_catalog/api/schemas.py — keep in sync (decision §11.18).

// ── Sample list / summary ────────────────────────────────────────────────

export type SampleSummary = {
  sample_id: string
  project: string
  data_source: string
  type: string | null
  cell_type: string | null
  description: string | null
  warning_count: number
  n_acquisitions: number
  n_tomograms: number
  n_tilt_series: number
}

// ── Sample detail: typed sub-entities (decision §11.18) ──────────────────

export type ChromatinOut = {
  substrate: string | null
  linker_length_bp: number | null
  linker_pattern: number[] | null
  linker_distribution: string | null
  buffer: string | null
  ptm: string | null
  histone_variants: string | null
  transcription_factors: string | null
  nucleosome_count: number | null
  dna_length_bp: number | null
  nucleosome_uM: number | null
  sequence_identity: string | null
  nucleosome_footprint: number[] | null
  linker_length_fraction: number | null
}

export type SynapseOut = {
  label_target: string | null
  label_strategy: string | null
}

export type SimulationOut = {
  dataset_type: string | null
}

export type FreezingOut = {
  grid_type: string | null
  cryoprotectant: string | null
  method: string | null
  planchette_size: string | null
  spacer_thickness: string | null
}

export type MillingOut = {
  scheme: string | null
  date: string | null
}

export type AunpOut = {
  ordinal: number
  size_nm: number | null
  type: string | null
  fluorophore: string | null
  concentration_value: number | null
  concentration_unit: string | null
  conjugation: string | null
  conjugation_target: string | null
  notes: string | null
}

export type TomogramOut = {
  tomogram_id: string
  pipeline: string | null
  software: string | null
  voxel_bin: number | null
  voxel_spacing_angstrom: number | null
  voxel_spacing_angstrom_implied: number | null
  derived_from: string[]
  is_raw: boolean | null
  image_size_x: number | null
  image_size_y: number | null
  image_size_z: number | null
  mrc_path: string | null
  zarr_path: string | null
  zarr_axes: string | null
  zarr_scale: number[] | null
  size_bytes: number | null
}

export type AnnotationOut = {
  annotation_id: string
  type: string | null
  target_tomogram: string | null
  files: string[]
}

export type TiltSeriesOut = {
  tilt_series_id: string
  mdoc_path: string | null
  st_path: string | null
  zarr_path: string | null
  n_tilts: number | null
  tilt_range_min: number | null
  tilt_range_max: number | null
  tilt_axis_angle: number | null
  voltage: number | null
  pixel_spacing: number | null
  image_format: string | null
  microscope: string | null
  camera: string | null
}

export type AcquisitionOut = {
  acquisition_id: string
  resolution: number | null
  microscope: string | null
  pixel_size: number | null
  voltage: number | null
  camera: string | null
  path: string | null
  tomograms: TomogramOut[]
  annotations: AnnotationOut[]
  tilt_series: TiltSeriesOut[]
}

export type SampleDetail = {
  sample_id: string
  project: string
  data_source: string
  type: string | null
  cell_type: string | null
  description: string | null
  chromatin: ChromatinOut | null
  synapse: SynapseOut | null
  simulation: SimulationOut | null
  freezing: FreezingOut | null
  milling: MillingOut | null
  aunp: AunpOut[]
  acquisitions: AcquisitionOut[]
}

// ── Filters / stats / viewers ────────────────────────────────────────────

export type RangeOut = {
  min: number | null
  max: number | null
}

export type FiltersOptionsOut = {
  projects: string[]
  data_sources: string[]
  types: string[]
  microscopes: string[]
  voltages: number[]
  cameras: string[]
  image_formats: string[]
  pixel_size: RangeOut
  voxel_spacing: RangeOut
  n_tilts: RangeOut
}

export type StatsTotalsOut = {
  samples: number
  acquisitions: number
  tilt_series: number
  tomograms: number
  annotations: number
  warnings: number
}

export type ProjectStatRow = {
  project: string
  samples: number
  acquisitions: number
  tomograms: number
  size_bytes: number
}

export type StatsOverviewOut = {
  totals: StatsTotalsOut
  by_project: ProjectStatRow[]
}

export type ViewerLaunchOut = {
  url: string
}

// ── Scan history / warnings / extras ─────────────────────────────────────

export type WarningOut = {
  id: number
  sample_id: string
  category: string
  location: string
  message: string
  detected_at: number
  scan_run_id: string
}

export type ScanOut = {
  scan_run_id: string
  started_at: number
  ended_at: number | null
  root: string
  status: string
  samples_upserted: number | null
  samples_skipped: number | null
  samples_failed: number | null
}

export type ExtrasSummaryRow = {
  entity_type: string
  key: string
  count: number
}
