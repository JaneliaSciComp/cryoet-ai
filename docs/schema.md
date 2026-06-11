# Database Model: CryoET + AI Portal

This document enumerates every field that will be stored in the portal database, organized by entity (Sample → Acquisition → Tomogram → Annotation). For each field it lists the data type and the **authoritative source**:

| Source | What it means |
|---|---|
| `sample.toml` | Researcher-authored sample-level metadata — one file at the sample root. Field definitions live in `schema.py`. Section shown in parentheses. |
| `acquisition.toml` | Researcher-authored per-acquisition parameters and processing log (`[raw_tomogram]`, `[[post_processed_tomogram]]`, `[[annotation]]` entries) — one file in each acquisition directory. Section shown in parentheses. |
| `MDOC` | Parsed from `.mdoc` files in the `Frames/` directory by `ingest_mdoc.py`. |
| `.eer` / `.tiff` | Derived from frame file extension or EER header metadata. |
| `MRC header` | Read from the `.mrc` file header on ingest. |
| `OME-Zarr .zattrs` | Read from the multiscale metadata in `.ome.zarr` arrays. |
| `directory` | Implicit from the prescribed directory structure (sample dir name, acquisition dir name, processing folder name). |
| `derived` | Computed on ingest from other DB fields (e.g., tilt range formatted string). |

Researcher-authored fields live in one of two files: sample-level metadata in `sample.toml` at the sample root, and per-acquisition parameters plus the processing log in `acquisition.toml` inside each acquisition directory. Both files are governed by `schema.py`; the section in parentheses identifies the TOML table (`[sample]`, `[chromatin]`, `[acquisition]`, `[raw_tomogram]`, `[[post_processed_tomogram]]`, etc.). Fields coming from any other source are **not** entered by researchers and are not duplicated in either TOML (no-duplication principle).

**Key annotations**: `(PK)` marks a **primary key** — the column that uniquely identifies each row in that table. `(FK)` marks a **foreign key** — a column whose value references the primary key of another table, used to link rows across entities (e.g., a tomogram's `acquisition_id` points back to its parent acquisition row).

---

## 1. Sample entity

One row per sample. Primary key: `sample_id` (the sample directory name).

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `sample_id` | text (PK) | `directory` | derived | Sample folder name. |
| `lab_name` | enum | `sample.toml` (`[sample]`) | researcher authored | `collepardo`, `gouaux`, `rosen`, or `villa` |
| `data_source` | enum | directory (top-level arm) | derived | `experimental` (under `Experimental/`) or `simulation` (under `MdSimulation/`). Not authored in `sample.toml`. |
| `project` | enum | `sample.toml` (`[sample]`) | researcher authored | `chromatin`, `synapse`, or `nanogold`. |
| `type` | text | `sample.toml` (`[sample]`) | researcher authored | e.g. `cellular` / `reconstituted`. |
| `cell_type` | text | `sample.toml` (`[sample]`) | researcher authored | Required when `type = cellular`. |
| `description` | text | `sample.toml` (`[sample]`) | researcher authored | Free text. |
| `path` | text | `directory` | derived | Absolute sample-directory path; surfaced for the UI's copy-path / open-in-file-browser buttons. Works even for samples with no acquisitions. |

### 1a. Chromatin sub-entity (one row per sample when `project = chromatin`)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `substrate` | text | `sample.toml` (`[chromatin]`) | researcher authored | e.g. `synthetic` / `native` / `n/a`. |
| `linker_length_bp` | float | `sample.toml` (`[chromatin]`) | researcher authored | Homogenous linker length. |
| `linker_pattern` | list[int] | `sample.toml` (`[chromatin]`) | researcher authored | Patterned linker lengths. |
| `linker_distribution` | text | `sample.toml` (`[chromatin]`) | researcher authored | Free-text distribution description. |
| `buffer` | text | `sample.toml` (`[chromatin]`) | researcher authored | Monovalent/divalent species + conc + additives. |
| `ptm` | text | `sample.toml` (`[chromatin]`) | researcher authored | |
| `histone_variants` | text | `sample.toml` (`[chromatin]`) | researcher authored | |
| `transcription_factors` | text | `sample.toml` (`[chromatin]`) | researcher authored | |
| `nucleosome_count` | integer | `sample.toml` (`[chromatin]`) | researcher authored | |
| `dna_length_bp` | integer | `sample.toml` (`[chromatin]`) | researcher authored | |
| `nucleosome_uM` | float | `sample.toml` (`[chromatin]`) | researcher authored | |
| `sequence_identity` | text | `sample.toml` (`[chromatin]`) | researcher authored | Native-substrate only. |
| `nucleosome_footprint` | list | `sample.toml` (`[chromatin]`) | researcher authored | Native-substrate only. |
| `linker_length_fraction` | float | `derived` | derived | `sequence_footprint − 1`; computed on ingest. |

### 1b. Label sub-entity (0..N per sample)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `label_target` | text | `sample.toml` (`[label]`) | researcher authored | |
| `aunp_type` | text | `sample.toml` (`[label]`) | researcher authored | |
| `aunp_size_nm` | float or list of floats | `sample.toml` (`[label]`) | researcher authored | |
| `conjugation` | text | `sample.toml` (`[label]`) | researcher authored | Fab / nanobody / chemical_tag / none. |
| `conjugation_target` | text | `sample.toml` (`[label]`) | researcher authored | e.g. GluA2. |
| `fluorophore` | text | `sample.toml` (`[label]`) | researcher authored | |
| `notes` | text | `sample.toml` (`[label]`) | researcher authored | |

### 1c. Fiducial AuNP (one per sample)

| Field | Type | Source | Source Type |
|---|---|---|---|
| `aunp_size_nm` | float or list of floats | `sample.toml` (`[fiducial]`) | researcher authored |
| `vendor` | text | `sample.toml` (`[fiducial]`) | researcher authored |
| `catalog_number` | text | `sample.toml` (`[fiducial]`) | researcher authored |
| `product_name` | text | `sample.toml` (`[fiducial]`) | researcher authored |
| `concentration_value` | float | `sample.toml` (`[fiducial]`) | researcher authored |
| `concentration_unit` | text | `sample.toml` (`[fiducial]`) | researcher authored |

### 1d. Freezing sub-entity (one per sample)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `grid_type` | text | `sample.toml` (`[freezing]`) | researcher authored | |
| `solution_type` | text | `sample.toml` (`[freezing]`) | researcher authored | |
| `cryoprotectant` | text | `sample.toml` (`[freezing]`) | researcher authored | |
| `method` | text | `sample.toml` (`[freezing]`) | researcher authored | `plunge_frozen` / `HPF`. |
| `planchette_size` | text | `sample.toml` (`[freezing]`) | researcher authored | HPF only. |
| `spacer_thickness` | text | `sample.toml` (`[freezing]`) | researcher authored | HPF only. |

### 1e. Milling sub-entity (one per sample)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `scheme` | text | `sample.toml` (`[milling]`) | researcher authored | |
| `date` | date | `sample.toml` (`[milling]`) | researcher authored | YYYY-MM-DD. |
| `quality` | text | `sample.toml` (`[milling]`) | researcher authored | |

### 1f. Simulation sub-entity (one row per sample when `data_source = simulation`)

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `dataset_type` | enum | `directory` (`MdSimulation/<SubDir>/`) | derived | One of `bulk`, `chromatin_fiber`, `single_molecule`, `slab` — derived from the `MdSimulation/{Bulk,ChromatinFiber,SingleMolecule,Slab}/` subdirectory, **not** authored in `sample.toml`. |

### 1g. MD run sub-entity (0..N per sample; simulation data only)

`MdRuns/{id}/md_run.toml` — one file per molecular-dynamics run, where the run's folder name under `{sample_dir}/MdRuns/{id}` *is* its identity (the `id` field is not authored, matching the sample/acquisition convention). Each folder holds that run's trajectories and frames. Rejected on `experimental` samples.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `md_run_id` | text (PK) | `directory` | derived | Run folder name under `MdRuns/` — the source of identity. |
| `seed` | integer | `MdRuns/{id}/md_run.toml` | researcher authored | RNG seed for the run. |
| `sample_time` | float | `MdRuns/{id}/md_run.toml` | researcher authored | Total simulated time. |
| `timestep` | float | `MdRuns/{id}/md_run.toml` | researcher authored | Integration timestep. |
| `computer` | text | `MdRuns/{id}/md_run.toml` | researcher authored | Name of the computer used. |
| `reference_contact` | text | `MdRuns/{id}/md_run.toml` | researcher authored | Reference or contact for the run. |
| `force_field_version` | text | `MdRuns/{id}/md_run.toml` | researcher authored | Force-field version used. |

---

## 2. Acquisition entity

One row per imaging position. Primary key: `(sample_id, acquisition_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `acquisition_id` | text (PK) | `directory` | derived | Acquisition folder name, e.g. `Position_86`. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample directory name. |
| `resolution` | float | `acquisition.toml` (`[acquisition]`) | researcher authored | Angstrom. Nominal target. |
| `tilt_spacing` | float | `acquisition.toml` (`[acquisition]`) | researcher authored | Degrees. Nominal step. |
| `defocus_range` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Micrometres, free-text range. |
| `energy_filter` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Model name. |
| `phase_plate` | boolean | `acquisition.toml` (`[acquisition]`) | researcher authored | |
| `microscope` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Model name. |
| `facility` | text | `acquisition.toml` (`[acquisition]`) | researcher authored | Imaging facility, e.g. `Janelia`. |
| `tilt_series_quality_score` | integer | `acquisition.toml` (`[acquisition]`) | researcher authored | 1–5 rubric: **5** Excellent, **4** Good, **3** Fair, **2** Poor, **1** Low. |
| `pixel_size` | float | `MDOC` | derived | Angstrom. |
| `dose_per_tilt` | list[float] | `MDOC` | derived | e/Å² per tilt. |
| `total_dose` | float | `MDOC` (summed) | derived | e/Å². |
| `tilt_min` | float | `MDOC` | derived | Degrees. Minimum tilt angle recorded. |
| `tilt_max` | float | `MDOC` | derived | Degrees. |
| `tilt_axis` | float | `MDOC` | derived | Degrees. |
| `defocus_per_image` | list[float] | `MDOC` | derived | Micrometres, per tilt. |
| `date_collected` | date | `MDOC` | derived | |
| `voltage` | float | `MDOC` | derived | kV. |
| `energy_filter_slit_width` | float | `MDOC` | derived | eV. |
| `camera` | text | `.eer` / `.tiff` | derived | Derived from frame extension (`.eer` → Falcon; `.tiff` → K3). |
| `frame_count` | integer | `MDOC` | derived | Number of tilts. |
| `path` | text | `directory` | derived | Absolute acquisition-directory path; surfaced for the UI's copy-path / open-in-file-browser buttons. Synthesized acquisitions record the directory the scanner walked. |

### 2a. Tilt series sub-entity (0..N per acquisition)

One row per tilt series within an acquisition. Primary key:
`(sample_id, acquisition_id, tilt_series_id)`, where `tilt_series_id` is the
MDOC stem (with a collision-disambiguating suffix when needed). These rows are
**not researcher-authored** — the catalog scanner is the canonical writer,
populating each row by parsing the acquisition's MDOC files and probing the
filesystem. They power the per-tilt-series UI cards (polar plot + median-tilt
preview + Neuroglancer launch). All non-PK fields are optional so a tilt series
can be ingested before MDOC parse succeeds.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `tilt_series_id` | text (PK) | `directory` / `MDOC` | derived | MDOC stem, with a collision-disambiguating suffix when needed. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `mdoc_path` | text | `directory` | derived | Path to the parsed `.mdoc` file. |
| `st_path` | text | `directory` | derived | Path to the stacked tilt-series file. |
| `zarr_path` | text | `directory` | derived | Path to the OME-Zarr rendering, when present. |
| `n_tilts` | integer | `MDOC` | derived | Number of tilt images in the series. |
| `tilt_range_min` | float | `MDOC` | derived | Degrees. Minimum tilt angle in the series. |
| `tilt_range_max` | float | `MDOC` | derived | Degrees. Maximum tilt angle in the series. |
| `tilt_axis_angle` | float | `MDOC` | derived | Degrees. Tilt-axis rotation. |
| `voltage` | float | `MDOC` | derived | kV. |
| `pixel_spacing` | float | `MDOC` | derived | Ångström. Per-series pixel spacing. |
| `image_format` | text | `MDOC` / frame extension | derived | One of `EER`, `TIFF`, `MRC`. |
| `microscope` | text | `MDOC` | derived | Model name. |
| `camera` | text | `MDOC` | derived | Detector name. |
| `tilt_angles` | list[float] | `MDOC` | derived | Full per-image angle list, cached on the row so polar-plot renders don't re-parse the MDOC. |
| `mtime` | float | `directory` | derived | MDOC modification time, used to gate re-parsing. |

### 2b. MD source sub-entity (one per acquisition; simulation data only)

`acquisition.toml` (`[md_source]`) — records which MD run + frame this acquisition's synthetic data came from. Rejected on `experimental` samples.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `md_run_id` | text (FK) | `acquisition.toml` (`[md_source]`) | researcher authored | Should match an `MdRuns/{id}/` folder name in the sample; a dangling ref warns rather than failing the acquisition. |
| `frame` | integer | `acquisition.toml` (`[md_source]`) | researcher authored | Frame/snapshot index within the MD run. |

---

## 3. Tomogram entities

Raw and post-processed tomograms are split into two tables. They share one
`tomogram_id` namespace within an acquisition: `derived_from` and an
annotation's `target_tomogram` may reference either a raw or a post-processed
tomogram in the same `acquisition.toml`.

### 3a. Raw tomogram (one row per acquisition, optional)

`acquisition.toml` (`[raw_tomogram]`) — at most one per acquisition. Primary key: `(sample_id, acquisition_id, tomogram_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `tomogram_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[raw_tomogram].id`) | researcher authored | Processing folder name, e.g. `bp_3dctf_bin4`; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `pipeline` | text | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | Human description. |
| `software` | text | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | |
| `voxel_size` | float | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | Ångström. Researcher-stated voxel spacing. |
| `voxel_spacing_angstrom` | float | `MRC header` | derived | DB-only column populated by the catalog scanner from the MRC header's `voxel_size.x`; not authored in any TOML. Cross-check against the authored `voxel_size`. |
| `derived_from` | list[text] | `acquisition.toml` (`[raw_tomogram]`) | researcher authored | Lineage; empty for raw reconstructions. |
| `image_size_x` | integer | `MRC header` | derived | |
| `image_size_y` | integer | `MRC header` | derived | |
| `image_size_z` | integer | `MRC header` | derived | |
| `mrc_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_axes` | text | `OME-Zarr .zattrs` | derived | Axis order. |
| `zarr_scale` | list[float] | `OME-Zarr .zattrs` | derived | Multiscale scale factors. |

### 3b. Post-processed tomogram (0..N per acquisition)

`acquisition.toml` (`[[post_processed_tomogram]]`) — one entry per processing output. Primary key: `(sample_id, acquisition_id, tomogram_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `tomogram_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[post_processed_tomogram]].id`) | researcher authored | Processing folder name; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `denoising_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | |
| `ctf_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | |
| `missing_wedge_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | |
| `voxel_size` | float | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | Ångström. Researcher-stated voxel spacing. |
| `voxel_spacing_angstrom` | float | `MRC header` | derived | DB-only column populated by the catalog scanner from the MRC header's `voxel_size.x`; not authored in any TOML. Cross-check against the authored `voxel_size`. |
| `derived_from` | list[text] | `acquisition.toml` (`[[post_processed_tomogram]]`) | researcher authored | Lineage; references a raw or post-processed `tomogram_id` in this acquisition. |
| `image_size_x` | integer | `MRC header` | derived | |
| `image_size_y` | integer | `MRC header` | derived | |
| `image_size_z` | integer | `MRC header` | derived | |
| `mrc_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_path` | text | `directory` | derived | Derived from prescribed layout. |
| `zarr_axes` | text | `OME-Zarr .zattrs` | derived | Axis order. |
| `zarr_scale` | list[float] | `OME-Zarr .zattrs` | derived | Multiscale scale factors. |
| `size_bytes` | integer | `filesystem` | derived | On-disk size recorded by the scanner via `os.stat` at parse time; powers the home-page size stats and per-card size badges. |

---

## 4. Annotation entity

One row per annotation output. Primary key: `(sample_id, acquisition_id, annotation_id)`.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `annotation_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[annotation]].id`) | researcher authored | Annotation folder name, e.g. `membrain_seg_v10`; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `type` | text | `acquisition.toml` (`[[annotation]]`) | researcher authored | e.g. `membrane_segmentation`, `nucleosome_placement`, `nucleosome_orientation`, `sta_result`. |
| `target_tomogram` | text (FK) | `acquisition.toml` (`[[annotation]]`) | researcher authored | Tomogram this was generated from. |
| `files` | list[text] | `directory` | derived | `.star`, `.mrc`, `.ome.zarr`, `.png` artifacts discovered in the folder. |

---

## 5. Alignment entity

One row per tilt-series alignment output. Primary key: `(sample_id, acquisition_id, alignment_id)`. Each `[[alignment]]` block in `acquisition.toml` corresponds to one `{alignment_id}/` subfolder under the acquisition's `Alignments/` directory.

| Field | Type | Source | Source Type | Notes |
|---|---|---|---|---|
| `alignment_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[alignment]].id`) | researcher authored | Alignment folder name under `Alignments/`, e.g. `imod_patch_v3`; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | derived | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | derived | Parent sample folder name. |
| `software` | text | `acquisition.toml` (`[[alignment]]`) | researcher authored | Alignment software (e.g. `IMOD`, `AreTomo3`). |
| `method` | text | `acquisition.toml` (`[[alignment]]`) | researcher authored | e.g. `fiducial`, `patch_tracking`, `feature_tracking`. |
| `files` | list[text] | `directory` | derived | Machine-emitted alignment artifacts discovered in the folder. |
