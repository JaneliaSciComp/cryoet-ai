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

Every item in the researcher's requested metadata list is cross-referenced in the rightmost column as `[researcher: <label>]`.

---

## 1. Sample entity

One row per sample. Primary key: `sample_id` (the sample directory name).

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `sample_id` | text (PK) | `directory` | Sample folder name. |
| `lab_name` | enum | `sample.toml` (`[sample]`) | | `collepardo`, `gouaux`, `rosen`, or `villa` |
| `data_source` | enum | `sample.toml` (`[sample]`) | `experimental` or `simulation`. |
| `project` | enum | `sample.toml` (`[sample]`) | `chromatin`, `synapse`, or `nanogold`. |
| `type` | text | `sample.toml` (`[sample]`) | e.g. `cellular` / `reconstituted`. [researcher: Cellular vs Reconstituted branch] |
| `cell_type` | text | `sample.toml` (`[sample]`) | Required when `type = cellular`. [researcher: Cell type] |
| `description` | text | `sample.toml` (`[sample]`) | Free text. |
| `path` | text | `directory` | Absolute sample-directory path; surfaced for the UI's copy-path / open-in-file-browser buttons. Works even for samples with no acquisitions. |

### 1a. Chromatin sub-entity (one row per sample when `project = chromatin`)

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `substrate` | text | `sample.toml` (`[chromatin]`) | e.g. `synthetic` / `native` / `n/a`. [researcher: Synthetic arrays vs Native sequences] |
| `linker_length_bp` | float | `sample.toml` (`[chromatin]`) | Homogenous linker length. [researcher: Linker length (homogenous)] |
| `linker_pattern` | list[int] | `sample.toml` (`[chromatin]`) | Patterned linker lengths. [researcher: Linker length (patterned)] |
| `linker_distribution` | text | `sample.toml` (`[chromatin]`) | Free-text distribution description. [researcher: Linker length (distribution)] |
| `buffer` | text | `sample.toml` (`[chromatin]`) | Monovalent/divalent species + conc + additives. [researcher: buffer conditions] |
| `ptm` | text | `sample.toml` (`[chromatin]`) | [researcher: post translational modifications] |
| `histone_variants` | text | `sample.toml` (`[chromatin]`) | [researcher: histone variants] |
| `transcription_factors` | text | `sample.toml` (`[chromatin]`) | [researcher: Transcription factors / binding proteins] |
| `nucleosome_count` | integer | `sample.toml` (`[chromatin]`) | [researcher: nucleosome number] |
| `dna_length_bp` | integer | `sample.toml` (`[chromatin]`) | [researcher: DNA length] |
| `nucleosome_uM` | float | `sample.toml` (`[chromatin]`) | [researcher: nucleosome concentration] |
| `sequence_identity` | text | `sample.toml` (`[chromatin]`) | Native-substrate only. [researcher: sequence identity] |
| `nucleosome_footprint` | list | `sample.toml` (`[chromatin]`) | Native-substrate only. [researcher: nucleosome footprint] |
| `linker_length_fraction` | float | `derived` | `sequence_footprint − 1`; computed on ingest. [researcher: linker length (size footprint-1)] |

### 1b. Label sub-entity (0..N per sample)

[researcher: Gold NP's]

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `label_target` | text | `sample.toml` (`[label]`) | |
| `aunp_type` | text | `sample.toml` (`[label]`) | [researcher: type] |
| `aunp_size_nm` | float or list of floats | `sample.toml` (`[label]`) | [researcher: Size] |
| `conjugation` | text | `sample.toml` (`[label]`) | Fab / nanobody / chemical_tag / none. [researcher: Conjugation partner] |
| `conjugation_target` | text | `sample.toml` (`[label]`) | e.g. GluA2. [researcher: Conjugation partner target] |
| `fluorophore` | text | `sample.toml` (`[label]`) | [researcher: Fluorophore] |
| `notes` | text | `sample.toml` (`[label]`) | |

### 1c. Fiducial AuNP (one per sample)

| Field | Type | Source |
|---|---|---|
| `aunp_size_nm` | float or list of floats | `sample.toml` (`[fiducial]`) |
| `vendor` | text | `sample.toml` (`[fiducial]`) |
| `catalog_number` | text | `sample.toml` (`[fiducial]`) |
| `product_name` | text | `sample.toml` (`[fiducial]`) |
| `concentration_value` | float | `sample.toml` (`[fiducial]`) |
| `concentration_unit` | text | `sample.toml` (`[fiducial]`) |

### 1d. Freezing sub-entity (one per sample)

[researcher: Freezing conditions]

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `grid_type` | text | `sample.toml` (`[freezing]`) | [researcher: grid type] |
| `solution_type` | text | `sample.toml` (`[freezing]`) | |
| `cryoprotectant` | text | `sample.toml` (`[freezing]`) | [researcher: cryo protectant] |
| `method` | text | `sample.toml` (`[freezing]`) | `plunge_frozen` / `HPF`. [researcher: freezing method] |
| `planchette_size` | text | `sample.toml` (`[freezing]`) | HPF only. [researcher: planchette size] |
| `spacer_thickness` | text | `sample.toml` (`[freezing]`) | HPF only. [researcher: spacer thickness] |

### 1e. Milling sub-entity (one per sample)

[researcher: Milling]

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `scheme` | text | `sample.toml` (`[milling]`) | [researcher: milling scheme] |
| `date` | date | `sample.toml` (`[milling]`) | YYYY-MM-DD. [researcher: date] |
| `quality` | text | `sample.toml` (`[milling]`) | |

### 1f. Simulation sub-entity (one row per sample when `data_source = simulation`)

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `dataset_type` | text | `sample.toml` (`[simulation]`) | e.g. `single_molecule` / `slab` / `bulk`. |

### 1g. MD run sub-entity (0..N per sample; simulation data only)

`sample.toml` (`[[md_run]]`) — one entry per molecular-dynamics run. Each `md_run_id` MUST match a directory under `{sample_dir}/MdRuns/{id}` (a simulation-only directory variation that holds that run's trajectories and frames). Rejected on `experimental` samples.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `md_run_id` | text (PK) | `directory` ↔ `sample.toml` (`[[md_run]].id`) | Run folder name under `MdRuns/`; the TOML `id` must match the folder. |
| `seed` | integer | `sample.toml` (`[[md_run]]`) | RNG seed for the run. |
| `computer` | text | `sample.toml` (`[[md_run]]`) | Name of the computer used. |

---

## 2. Acquisition entity

One row per imaging position. Primary key: `(sample_id, acquisition_id)`.

[researcher: Tomogram level → Acquisition Scheme + Acquisition Type]

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `acquisition_id` | text (PK) | `directory` | Acquisition folder name, e.g. `Position_86`. |
| `sample_id` | text (FK) | `directory` | Parent sample directory name. |
| `resolution` | float | `acquisition.toml` (`[acquisition]`) | Angstrom. Nominal target. [researcher: Resolution] |
| `tilt_spacing` | float | `acquisition.toml` (`[acquisition]`) | Degrees. Nominal step. [researcher: tilt spacing] |
| `defocus_range` | text | `acquisition.toml` (`[acquisition]`) | Micrometres, free-text range. [researcher: defocus range] |
| `energy_filter` | text | `acquisition.toml` (`[acquisition]`) | Model name. [researcher: energy filter] |
| `phase_plate` | boolean | `acquisition.toml` (`[acquisition]`) | [researcher: phase plate] |
| `microscope` | text | `acquisition.toml` (`[acquisition]`) | Model name. [researcher: scope type] |
| `quality` | text | `acquisition.toml` (`[acquisition]`) | e.g., "high", "medium", "low" |
| `pixel_size` | float | `MDOC` | Angstrom. [researcher: pixel size] |
| `dose_per_tilt` | list[float] | `MDOC` | e/Å² per tilt. [researcher: dose] |
| `total_dose` | float | `MDOC` (summed) | e/Å². [researcher: dose (total)] |
| `tilt_min` | float | `MDOC` | Degrees. Minimum tilt angle recorded. [researcher: tilt range (min)] |
| `tilt_max` | float | `MDOC` | Degrees. [researcher: tilt range (max)] |
| `tilt_axis` | float | `MDOC` | Degrees. [researcher: tilt axis] |
| `defocus_per_image` | list[float] | `MDOC` | Micrometres, per tilt. |
| `date_collected` | date | `MDOC` | [researcher: date of collection] |
| `voltage` | float | `MDOC` | kV. [researcher: operating voltage] |
| `energy_filter_slit_width` | float | `MDOC` | eV. [researcher: energy filter slit width] |
| `camera` | text | `.eer` / `.tiff` | Derived from frame extension (`.eer` → Falcon; `.tiff` → K3). [researcher: Camera] |
| `frame_count` | integer | `MDOC` | Number of tilts. |
| `path` | text | `directory` | Absolute acquisition-directory path; surfaced for the UI's copy-path / open-in-file-browser buttons. Synthesized acquisitions record the directory the scanner walked. |

### 2a. Tilt series sub-entity (0..N per acquisition)

One row per tilt series within an acquisition. Primary key:
`(sample_id, acquisition_id, tilt_series_id)`, where `tilt_series_id` is the
MDOC stem (with a collision-disambiguating suffix when needed). These rows are
**not researcher-authored** — the catalog scanner is the canonical writer,
populating each row by parsing the acquisition's MDOC files and probing the
filesystem. They power the per-tilt-series UI cards (polar plot + median-tilt
preview + Neuroglancer launch). All non-PK fields are optional so a tilt series
can be ingested before MDOC parse succeeds.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `tilt_series_id` | text (PK) | `directory` / `MDOC` | MDOC stem, with a collision-disambiguating suffix when needed. |
| `acquisition_id` | text (FK) | `directory` | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | Parent sample folder name. |
| `mdoc_path` | text | `directory` | Path to the parsed `.mdoc` file. |
| `st_path` | text | `directory` | Path to the stacked tilt-series file. |
| `zarr_path` | text | `directory` | Path to the OME-Zarr rendering, when present. |
| `n_tilts` | integer | `MDOC` | Number of tilt images in the series. |
| `tilt_range_min` | float | `MDOC` | Degrees. Minimum tilt angle in the series. |
| `tilt_range_max` | float | `MDOC` | Degrees. Maximum tilt angle in the series. |
| `tilt_axis_angle` | float | `MDOC` | Degrees. Tilt-axis rotation. |
| `voltage` | float | `MDOC` | kV. |
| `pixel_spacing` | float | `MDOC` | Ångström. Per-series pixel spacing. |
| `image_format` | text | `MDOC` / frame extension | One of `EER`, `TIFF`, `MRC`. |
| `microscope` | text | `MDOC` | Model name. |
| `camera` | text | `MDOC` | Detector name. |
| `tilt_angles` | list[float] | `MDOC` | Full per-image angle list, cached on the row so polar-plot renders don't re-parse the MDOC. |
| `mtime` | float | `directory` | MDOC modification time, used to gate re-parsing. |

### 2b. MD source sub-entity (one per acquisition; simulation data only)

`acquisition.toml` (`[md_source]`) — records which MD run + frame this acquisition's synthetic data came from. Rejected on `experimental` samples.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `md_run_id` | text (FK) | `acquisition.toml` (`[md_source]`) | MUST match an `md_run_id` in the sample's `sample.toml` `[[md_run]]`. |
| `frame` | integer | `acquisition.toml` (`[md_source]`) | Frame/snapshot index within the MD run. |

---

## 3. Tomogram entities

[researcher: Processing level → Raw tomogram / Processed tomograms]

Raw and post-processed tomograms are split into two tables. They share one
`tomogram_id` namespace within an acquisition: `derived_from` and an
annotation's `target_tomogram` may reference either a raw or a post-processed
tomogram in the same `acquisition.toml`.

### 3a. Raw tomogram (one row per acquisition, optional)

`acquisition.toml` (`[raw_tomogram]`) — at most one per acquisition. Primary key: `(sample_id, acquisition_id, tomogram_id)`.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `tomogram_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[raw_tomogram].id`) | Processing folder name, e.g. `bp_3dctf_bin4`; the TOML `id` must match the folder. [researcher: Processing Steps] |
| `acquisition_id` | text (FK) | `directory` | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | Parent sample folder name. |
| `pipeline` | text | `acquisition.toml` (`[raw_tomogram]`) | Human description. [researcher: Processing Steps] |
| `software` | text | `acquisition.toml` (`[raw_tomogram]`) | [researcher: software] |
| `voxel_size` | float | `acquisition.toml` (`[raw_tomogram]`) | Ångström. Researcher-stated voxel spacing. |
| `voxel_spacing_angstrom` | float | `MRC header` | DB-only column populated by the catalog scanner from the MRC header's `voxel_size.x`; not authored in any TOML. Cross-check against the authored `voxel_size`. |
| `derived_from` | list[text] | `acquisition.toml` (`[raw_tomogram]`) | Lineage; empty for raw reconstructions. |
| `image_size_x` | integer | `MRC header` | [researcher: image size] |
| `image_size_y` | integer | `MRC header` | |
| `image_size_z` | integer | `MRC header` | |
| `mrc_path` | text | `directory` | Derived from prescribed layout. |
| `zarr_path` | text | `directory` | Derived from prescribed layout. |
| `zarr_axes` | text | `OME-Zarr .zattrs` | Axis order. |
| `zarr_scale` | list[float] | `OME-Zarr .zattrs` | Multiscale scale factors. |

### 3b. Post-processed tomogram (0..N per acquisition)

`acquisition.toml` (`[[post_processed_tomogram]]`) — one entry per processing output. Primary key: `(sample_id, acquisition_id, tomogram_id)`.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `tomogram_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[post_processed_tomogram]].id`) | Processing folder name; the TOML `id` must match the folder. [researcher: Processing Steps] |
| `acquisition_id` | text (FK) | `directory` | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | Parent sample folder name. |
| `denoising_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | [researcher: software] |
| `ctf_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | [researcher: software] |
| `missing_wedge_software` | text | `acquisition.toml` (`[[post_processed_tomogram]]`) | [researcher: software] |
| `voxel_size` | float | `acquisition.toml` (`[[post_processed_tomogram]]`) | Ångström. Researcher-stated voxel spacing. |
| `voxel_spacing_angstrom` | float | `MRC header` | DB-only column populated by the catalog scanner from the MRC header's `voxel_size.x`; not authored in any TOML. Cross-check against the authored `voxel_size`. |
| `derived_from` | list[text] | `acquisition.toml` (`[[post_processed_tomogram]]`) | Lineage; references a raw or post-processed `tomogram_id` in this acquisition. |
| `image_size_x` | integer | `MRC header` | [researcher: image size] |
| `image_size_y` | integer | `MRC header` | |
| `image_size_z` | integer | `MRC header` | |
| `mrc_path` | text | `directory` | Derived from prescribed layout. |
| `zarr_path` | text | `directory` | Derived from prescribed layout. |
| `zarr_axes` | text | `OME-Zarr .zattrs` | Axis order. |
| `zarr_scale` | list[float] | `OME-Zarr .zattrs` | Multiscale scale factors. |
| `size_bytes` | integer | `filesystem` | On-disk size recorded by the scanner via `os.stat` at parse time; powers the home-page size stats and per-card size badges. |

---

## 4. Annotation entity

[researcher: Processing level → Segmentation / Nucleosome orientation / STA results]

One row per annotation output. Primary key: `(sample_id, acquisition_id, annotation_id)`.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `annotation_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[annotation]].id`) | Annotation folder name, e.g. `membrain_seg_v10`; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | Parent sample folder name. |
| `type` | text | `acquisition.toml` (`[[annotation]]`) | e.g. `membrane_segmentation`, `nucleosome_placement`, `nucleosome_orientation`, `sta_result`. [researcher: Segmentation / Nucleosome orientation / STA results] |
| `target_tomogram` | text (FK) | `acquisition.toml` (`[[annotation]]`) | Tomogram this was generated from. |
| `files` | list[text] | `directory` | `.star`, `.mrc`, `.ome.zarr`, `.png` artifacts discovered in the folder. |

---

## 5. Alignment entity

One row per tilt-series alignment output. Primary key: `(sample_id, acquisition_id, alignment_id)`. Each `[[alignment]]` block in `acquisition.toml` corresponds to one `{alignment_id}/` subfolder under the acquisition's `Alignments/` directory.

| Field | Type | Source | Notes / researcher mapping |
|---|---|---|---|
| `alignment_id` | text (PK) | `directory` ↔ `acquisition.toml` (`[[alignment]].id`) | Alignment folder name under `Alignments/`, e.g. `imod_patch_v3`; the TOML `id` must match the folder. |
| `acquisition_id` | text (FK) | `directory` | Parent acquisition folder name. |
| `sample_id` | text (FK) | `directory` | Parent sample folder name. |
| `software` | text | `acquisition.toml` (`[[alignment]]`) | Alignment software (e.g. `IMOD`, `AreTomo3`). |
| `method` | text | `acquisition.toml` (`[[alignment]]`) | e.g. `fiducial`, `patch_tracking`, `feature_tracking`. |
| `files` | list[text] | `directory` | Machine-emitted alignment artifacts discovered in the folder. |
