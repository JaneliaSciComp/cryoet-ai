# Data organization & metadata

This document describes the on-disk layout and TOML metadata scheme for the CryoET + AI project. It is the authoring guide for researchers and the contract that the catalog scanner (`catalog`) reads against.

The central design goal is answering one question across both the experimental and simulation arms of the project: **which conditions have we covered, and which still need cryoET imaging, simulation, or both?**

> **Status: draft / proposed.** Fields, controlled vocabularies, and directory conventions are expected to evolve as researchers start authoring metadata against it.

---

## Quick start: Researcher workflow for creating a new sample directory and adding metadata

### 0. (Optional) Set up VSCode for live TOML validation

Authoring TOML in **VSCode** with the [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) extension gives you in-editor type checking, enum suggestions, and field hints as you fill in the templates. The `#:schema` directive at the top of each template points the extension at `src/schema/schema.json` (for `sample.toml`) and `src/schema/acquisition.schema.json` (for `acquisition.toml`).

Skipping the editor setup is fine — `pixi run validate {sample_dir}` (step 5) catches the same errors at the end.

### 1. Lay out the sample directory

Copy the starter directory that matches your data arm — `templates/sample_id_experimental/` for experimental cryoET data or `templates/sample_id_simulation/` for MD + synthetic cryoET data — into the right top-level arm: experimental samples go under `Experimental/`, and simulation samples go under `MdSimulation/{Bulk|ChromatinFiber|SingleMolecule|Slab}/` (the subdirectory you choose sets the sample's `dataset_type`). The starter directory contains empty directories to scaffold the correct directory structure. Then follow the naming instructions below.

Rename the top-level `sample_id_*` directory to the desired sample id.

```
gouauxlab_20250418_AMmilled29-2/
```

Inside, make a copy of `acquisition_id`. Then update one of the directories to the desired acquisition id for your first acquisition. Repeat this process every time you want to add a new acquisition. (For simulation samples, the `acquisition_id` template lives inside `SyntheticCryoET/`; copy and rename it there.)

```
gouauxlab_20250418_AMmilled29-2/
  Position_86/
  Position_87/
```

### 2. Fill out `{sample_id}/sample.toml`

- Complete as many fields marked `<FILL IN>` as you can. For now, the only required authored field is `sample.project` (`sample.data_source` is set by the directory the sample lives under, not authored).
- Delete the `[synapse]` block if your project is `chromatin`, or vice versa.
- Optionally, uncomment and complete the `[[aunp]]`, `[freezing]`, and `[milling]` blocks.

### 3. Fill out `{sample_id}/{acquisition_id}/acquisition.toml` in each acquisition directory

- Complete as many fields marked `<FILL IN>` as you can. For now, no fields are required.

### 4. Append to the processing log as outputs are produced

Each `acquisition.toml` grows over time. Record the raw reconstruction once in `[raw_tomogram]`; for each new output — a denoised version, a segmentation, an STA result — append a new `[[post_processed_tomogram]]` or `[[annotation]]` entry to the relevant acquisition's file.

**Rules:**
- Do **not** delete or modify a tomogram or annotation entry once added. Reprocessing produces a **new** entry with a new `id`, placed at the bottom of the file.
- The `id` must match one folder name under `Reconstructions/Tomograms/`, `Reconstructions/Annotations/`, or `Alignments/`.
- Use `derived_from` and `target_tomogram` to record lineage (see above).

### 5. Validate

The validate script checks `sample.toml` and every `acquisition.toml` under the sample directory and reports any fields that violate the schema. Validation also runs during database ingestion — see `docs/schema.md` for the full list of fields that will be stored, including those auto-derived from MDOCs, MRC headers, OME-Zarr metadata, and directory structure.

#### Option 1: With pixi

1. [Install pixi](https://pixi.prefix.dev/latest/installation/).
2. The first time you use pixi for this repo, run `pixi install` to install the environment.
3. Run the validation with this command:

```
pixi run validate {sample_dir}
```

#### Option 2: Without pixi

Alternatively, you can run the validator with any Python ≥3.11 — the only runtime dependencies are `pydantic` and `rapidfuzz`, both pure-Python.

For example, using Python's built-in `venv` module:

```bash
# from the repo root
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
python -m schema.validate {sample_dir}
```

`pip install -e .` reads the same dependency list pixi uses (`[project.dependencies]` in `pyproject.toml`).

[`uv`](https://docs.astral.sh/uv/) works as a drop-in for `pip`/`venv`.

---

## Directory structure

The data root has **two top-level arms**, and the arm a sample lives under is
the source of truth for its `data_source` (and, for simulation, its
`dataset_type`):

```
{data_root}/
  Experimental/                              # data_source = experimental
    {sample_id}/ ...
  MdSimulation/                              # data_source = simulation
    Bulk/            {sample_id}/ ...        # dataset_type = bulk
    ChromatinFiber/  {sample_id}/ ...        # dataset_type = chromatin_fiber
    SingleMolecule/  {sample_id}/ ...        # dataset_type = single_molecule
    Slab/            {sample_id}/ ...        # dataset_type = slab
```

`data_source` is derived from the top-level directory (`Experimental` vs
`MdSimulation`), and a simulation sample's `dataset_type` is derived from the
`MdSimulation/<SubDir>/` it sits under — **neither is authored in
`sample.toml`**. Any `data_source` left over in a legacy `sample.toml` is
simply overridden by the directory.

### CryoET (experimental) data — under `Experimental/`

```
Experimental/
  {sample_id}/                               # sample identity = directory name
    sample.toml                              # sample-level conditions
    {acquisition_id}/                        # acquisition identity = directory name
      acquisition.toml                       # per-acquisition params + processing log
      Frames/                                # raw movie frames (.eer / .tiff) + .mdoc
      Gains/                                 # gain reference
      TiltSeries/                            # .mrc + .zarr + .rawtlt
      Alignments/
        {alignment_id}/                      # one subfolder per alignment run
          *.json                             # machine-emitted alignment files
      Reconstructions/
        Tomograms/
          {processing_id}/                   # one subfolder per processing pipeline
            *.mrc
            *.zarr
        Annotations/
          {annotation_id}/
            *.star
            *.mrc / *.zarr
```

### MD simulation (sample) and associated synthetic cryoET (acquisitions) data — under `MdSimulation/<SubDir>/`

```
MdSimulation/{Bulk|ChromatinFiber|SingleMolecule|Slab}/
  {sample_id}/
    sample.toml                              # sample-level conditions
    MdRuns/                                  # simulation only: one subfolder per MD run
      {md_run_id}/                           # the folder name IS the run's id
        md_run.toml                          # seed, sample_time, timestep, computer, …
        Trajectories/                        # raw simulation output
        Snapshots/                           # extracted conformations (frames)
    SyntheticCryoET/                         # wraps all synthetic-cryoET acquisitions for this sample
      {acquisition_id}/                      # synthetic cryoET from one md_run frame
        acquisition.toml                     # per-acquisition params + [md_source]
        TiltSeries/
        Reconstructions/
          Tomograms/
            {processing_id}/                 # one subfolder per processing pipeline
              *.mrc
              *.zarr
          Annotations/
            {annotation_id}/
              *.star
              *.mrc / *.zarr
```

For simulation samples, the raw MD data lives under `MdRuns/{md_run_id}/` — one
subfolder per MD run. Each run is described by its own `MdRuns/{id}/md_run.toml`
file, and the **folder name is the run's identity** (`md_run_id`); there is no
`id` field authored in the file. Each acquisition is the synthetic cryoET
generated from a single frame of one run; its directory sits inside
`SyntheticCryoET/`, sibling to `MdRuns/`, and its `[md_source]` block records
which `md_run_id` and `frame` it came from. The `md_source.md_run_id` should
match an `MdRuns/{id}/` folder name; a dangling reference warns rather than
failing the acquisition. Both `MdRuns/{id}/md_run.toml` and `[md_source]` are
relevant only to simulation samples and are rejected on experimental samples.

The directory skeleton is adapted from the [CZI CryoET Data Portal](https://chanzuckerberg.github.io/cryoet-data-portal/stable/cryoet_data_portal_docsite_data.html) at the Sample > Acquisition > (Frames, Gains, TiltSeries, Alignments, Reconstructions) level, with three deliberate departures:

- **Two metadata files per sample.** Sample-level conditions live in `sample.toml` at the sample root. Per-acquisition parameters and the processing log live in `{acquisition}/acquisition.toml`. Fields derivable from MDOC files and file headers are authored in neither file; the ingest pipeline will read them directly.
- **Tomograms are kept in per-pipeline subfolders** (e.g., `bp_3dctf_bin4/`, `bp_3dctf_bin4_ddw/`) rather than flattened into `Tomograms/`. This avoids filename collisions when new processing versions are added, and the folder name acts as the `processing_id`.
- **No `VoxelSpacing{N}/` subfolder.** Voxel spacing in Ångström is recorded directly in `acquisition.toml` (as `voxel_size` on the `[raw_tomogram]` and each `[[post_processed_tomogram]]` entry); the catalog scanner also reads the value straight from the MRC header for cross-checking. Keeping voxel info out of the path avoids duplicating information that lives in the file itself.

Simulation data uses a parallel structure with domain-appropriate folder names. Both share the same schema, which is what makes cross-comparison possible.

### Example: mapping Gouaux lab data to this structure

This experimental sample lives under the `Experimental/` top-level arm:

```
Experimental/
gouauxlab_20250418_AMmilled29-2/             # sample identity = directory name
  sample.toml                                # sample-level conditions
  Position_86/                               # acquisition identity = directory name
    acquisition.toml                         # per-acquisition params + processing log
    Frames/
      *.eer
      *.eer.mdoc                             # acquisition metadata lives here
    Gains/
      gain_reference.gain
    TiltSeries/                              # TO CREATE: from .eer conversion
      *.mrc
      *.zarr
      *.rawtlt
    Alignments/
      imod_patch_v3/                         # one subfolder per alignment run
        *.json
    Reconstructions/
      Tomograms/
        bp_3dctf_bin4/                       # renamed from "raw/"
          *_BP_3DCTF_BIN4.mrc
          *_BP_3DCTF_BIN4.zarr
        bp_3dctf_bin4_ddw/                   # renamed from "ddw/"
          *_BP_3DCTF_BIN4_ddw.mrc
          *_BP_3DCTF_BIN4_ddw.zarr
      Annotations/
        activezone_1/                        # renamed to match star-file id
          activezone_1.star
          active_zonogram_0.mrc
          active_zonogram_0.zarr
          active_zonogram_0_annotated.png
        membrain_seg_v10/
          *_MemBrain_seg_v10_*_smooth.mrc
          *_MemBrain_seg_v10_*_smooth.zarr
  Position_87/
    acquisition.toml
    Frames/
    ...
```

Changes from the current `annotation_HHMI_reorg` layout:

1. Rename `raw/` → `bp_3dctf_bin4/` and `ddw/` → `bp_3dctf_bin4_ddw/`.
2. Rename `activezone/` → `activezone_{N}/` to match the star-file id (schema rule: annotation `id` = folder name).
3. Add `sample.toml` at the sample level.
4. Add `acquisition.toml` in each acquisition directory.
5. Create `TiltSeries/` (pending `.eer` conversion).

---

## Metadata files

### `sample.toml` — sample-level conditions

One file per sample, placed at the root of the sample directory. Contains only what was imaged or simulated — not how. The sample directory name *is* the sample's identity, so `sample.id` is omitted from the file.

### `acquisition.toml` — per-acquisition parameters + processing log

One file per acquisition, placed at the root of each acquisition directory. It contains:

1. Researcher-authored imaging parameters not available from MDOC files (nominal resolution, nominal tilt spacing, target defocus range, energy filter model, phase plate, microscope model, imaging `facility`).
2. A **tilt-series quality score** (`tilt_series_quality_score`): an integer on a 1–5 rubric — **5** Excellent, **4** Good, **3** Fair, **2** Poor, **1** Low. (This replaces the former free-text `quality` field, which has been removed.)
3. A **processing log**: a `[raw_tomogram]` table plus `[[post_processed_tomogram]]` and `[[annotation]]` entries appended over time as processing produces new outputs.

The acquisition directory name *is* the acquisition's identity, so `acquisition.id` is omitted from the file.

### `md_run.toml` — per-MD-run metadata (simulation samples only)

One file per MD run, placed at the root of each `MdRuns/{id}/` directory. The run directory name *is* the run's identity (`md_run_id`), so no `id` field is authored. It records the run's `seed`, `sample_time`, `timestep`, `computer`, `reference_contact`, and `force_field_version`. (This replaces the deprecated `[[md_run]]` blocks in `sample.toml`.)

---

## Schema rules

### Required fields

The only required authored field is `sample.project`. `sample.data_source` is set by the top-level directory (`Experimental/` vs `MdSimulation/`) and `dataset_type` by the `MdSimulation/<SubDir>/` directory — both are derived, not authored. All other fields are optional, allowing the schema to grow as researcher needs settle. The schema enums are `data_source`, `dataset_type`, `project`, and `lab_name` (authored under `[sample]`; one of `collepardo`, `gouaux`, `rosen`, `villa`) — all other fields are open text, with the potential to be tightened into enums later based on how researchers use them.

### Folder naming rules

Five folder names become primary keys in the portal database: the sample directory (`sample_id`), each acquisition directory (`acquisition_id`), each tomogram processing subfolder (`tomogram_id`), each annotation subfolder (`annotation_id`), and each alignment subfolder (`alignment_id`). The same strings may also be used in path expressions, URLs, and shell commands, so they are restricted to a conservative, cross-platform-safe allowlist.

A valid id must:

- be 1–128 characters long,
- contain only letters, numbers, `.`, `_`, and `-`,
- start and end with a letter or number,
- not contain `..`

### Extra fields

You may add any key-value pair to any section of `sample.toml` or `acquisition.toml` that is not yet in the schema. For example:

```toml
[chromatin]
substrate        = "synthetic"
linker_length_bp = 187.0
# Fields not yet in schema.py — captured here for later formalization:
ionic_strength_mM = 154.0
assembly_method   = "salt_dialysis"
```

Each Pydantic model is configured with `extra="allow"`, so unknown keys are preserved on the parsed record. The validator walks the tree after validation and reports every extra key as a **warning**, not an error — the file still passes and the extra fields survive into the ingest record. If a field proves useful, notify the SciComp team so it can be formally added to `schema.py` with the appropriate type and description.

### Lineage: `derived_from` and `target_tomogram`

`derived_from` records lineage across tomogram entries, and `target_tomogram` links annotations to the tomogram they were generated from. Both reference ids within the same `acquisition.toml`:

```toml
# In .../Position_86/acquisition.toml

# Raw reconstruction (at most one [raw_tomogram] per acquisition)
[raw_tomogram]
id                     = "bp_3dctf_bin4"
voxel_size             = 4.0
derived_from           = []

# Denoised version derived from the raw
[[post_processed_tomogram]]
id                     = "bp_3dctf_bin4_ddw"
voxel_size             = 4.0
derived_from           = ["bp_3dctf_bin4"]

# Segmentation run on the denoised tomogram
[[annotation]]
id              = "membrain_seg_v10"
type            = "membrane_segmentation"
target_tomogram = "bp_3dctf_bin4_ddw"
```
