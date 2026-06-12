// Hand-written mirror of catalog/api/schemas.py — keep in sync.

// ── Sample list / summary ────────────────────────────────────────────────

export type SampleSummary = {
  sample_id: string
  project: string
  lab_name: string | null
  data_source: string
  type: string | null
  cell_type: string | null
  description: string | null
  path: string | null
  warning_count: number
  // Total child-row counts intrinsic to the sample — filter-independent.
  // ``n_tomograms`` is summed across raw + post-processed tables.
  n_acquisitions: number
  n_tomograms: number
  n_tilt_series: number
  thumbnail_path: string | null
}

// ── Sample detail: typed sub-entities ────────────────────────────────────

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

export type LabelOut = {
  ordinal: number
  label_target: string | null
  aunp_type: string | null
  // Polymorphic — single size or a list of sizes.
  aunp_size_nm: number | number[] | null
  conjugation: string | null
  conjugation_target: string | null
  fluorophore: string | null
  notes: string | null
}

export type FiducialOut = {
  aunp_size_nm: number | null
  vendor: string | null
  catalog_number: string | null
  product_name: string | null
  concentration_value: number | null
  concentration_unit: string | null
}

export type SimulationOut = {
  dataset_type: string | null
}

export type FreezingOut = {
  grid_type: string | null
  solution_type: string | null
  cryoprotectant: string | null
  method: string | null
  planchette_size: string | null
  spacer_thickness: string | null
}

export type MillingOut = {
  scheme: string | null
  date: string | null
  quality: string | null
}

export type MdRunOut = {
  md_run_id: string
  seed: number | null
  computer: string | null
  sample_time: number | null
  timestep: number | null
  reference_contact: string | null
  force_field_version: string | null
}

// Fields shared between raw and post-processed tomogram outputs.
type TomogramOutBase = {
  tomogram_id: string
  voxel_size: number | null
  derived_from: string[]
  image_size_x: number | null
  image_size_y: number | null
  image_size_z: number | null
  mrc_path: string | null
  zarr_path: string | null
  zarr_axes: string | null
  zarr_scale: number[] | null
}

export type RawTomogramOut = TomogramOutBase & {
  pipeline: string | null
  software: string | null
}

export type PostProcessedTomogramOut = TomogramOutBase & {
  denoising_software: string | null
  ctf_software: string | null
  missing_wedge_software: string | null
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

export type MdSourceOut = {
  md_run_id: string | null
  frame: number | null
}

export type AcquisitionOut = {
  acquisition_id: string
  resolution: number | null
  microscope: string | null
  facility: string | null
  tilt_series_quality_score: number | null
  pixel_size: number | null
  voltage: number | null
  camera: string | null
  path: string | null
  md_source: MdSourceOut | null
  raw_tomogram: RawTomogramOut | null
  post_processed_tomograms: PostProcessedTomogramOut[]
  annotations: AnnotationOut[]
  tilt_series: TiltSeriesOut[]
}

export type SampleDetail = {
  sample_id: string
  project: string
  lab_name: string | null
  data_source: string
  type: string | null
  cell_type: string | null
  description: string | null
  path: string | null
  chromatin: ChromatinOut | null
  fiducial: FiducialOut | null
  simulation: SimulationOut | null
  freezing: FreezingOut | null
  milling: MillingOut | null
  label: LabelOut[]
  md_run: MdRunOut[]
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
  voxel_size: RangeOut
  n_tilts: RangeOut
}

export type StatsTotalsOut = {
  samples: number
  acquisitions: number
  tilt_series: number
  // Sum across raw + post-processed tomogram tables.
  tomograms: number
  annotations: number
  warnings: number
}

export type ProjectStatRow = {
  project: string
  samples: number
  acquisitions: number
  // Sum across raw + post-processed tomogram tables.
  tomograms: number
  // Sum across PostProcessedTomogramOut.size_bytes only — RawTomogram has
  // no size_bytes field in the schema.
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

// A sample's outcome within a scan run (drives the /manage tables).
// data_source/project/type are null for failed samples never persisted;
// detail carries the error message for failed outcomes.
export type ScanSampleOut = {
  sample_id: string
  data_source: string | null
  project: string | null
  type: string | null
  warning_count: number
  detail: string | null
}

// All warning messages for a single sample in the latest completed scan.
export type SampleWarningsGroup = {
  sample_id: string
  warnings: string[]
}

// A run-level warning not tied to any sample (e.g. an unknown subdirectory
// under MdSimulation/ that was skipped during discovery).
export type RunWarningOut = {
  id: number
  category: string
  location: string
  message: string
  detected_at: number
  scan_run_id: string
}
