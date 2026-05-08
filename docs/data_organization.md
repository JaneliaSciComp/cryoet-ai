# Data organization & metadata

This document describes the on-disk layout and TOML metadata scheme for the CryoET + AI project. It is the authoring guide for researchers and the contract that the catalog scanner (`cryoet_catalog`) reads against.

The central design goal is answering one question across both the experimental and simulation arms of the project: **which conditions have we covered, and which still need cryoET imaging, simulation, or both?**

> **Status: draft / proposed.** Fields, controlled vocabularies, and directory conventions are expected to evolve as researchers start authoring metadata against it.

---

## Directory structure

### CryoET (experimental) data

```
{sample_name}/                               # sample identity = directory name
  sample.toml                                # sample-level conditions
  {acquisition_name}/                        # acquisition identity = directory name
    acquisition.toml                         # per-acquisition params + processing log
    Frames/                                  # raw movie frames (.eer / .tiff) + .mdoc
    Gains/                                   # gain reference
    TiltSeries/                              # .mrc + .zarr + .rawtlt
    Alignments/                              # per-alignment .json (machine-emitted)
    Reconstructions/
      Tomograms/
        {processing_id}/                     # one subfolder per processing pipeline
          *.mrc
          *.zarr
      Annotations/
        {annotation_id}/
          *.star
          *.mrc / *.zarr
```

### MD simulation data

```
{sample_name}/
  sample.toml                                # sample-level conditions + simulation params
  {acquisition_name}/
    acquisition.toml                         # per-acquisition params + processing log
    Trajectories/                            # raw simulation output
    Snapshots/                               # extracted conformations
    SyntheticCryoET/                         # simulated tomograms generated from snapshots
      {processing_id}/
        *.mrc
        *.zarr
```

The directory skeleton is adapted from the [CZI CryoET Data Portal](https://chanzuckerberg.github.io/cryoet-data-portal/stable/cryoet_data_portal_docsite_data.html) at the Sample > Acquisition > (Frames, Gains, TiltSeries, Alignments, Reconstructions) level, with three deliberate departures:

- **Two metadata files per sample.** Sample-level conditions live in `sample.toml` at the sample root. Per-acquisition parameters and the processing log live in `{acquisition}/acquisition.toml`. Fields derivable from MDOC files and file headers are authored in neither file; the ingest pipeline will read them directly.
- **Tomograms are kept in per-pipeline subfolders** (e.g., `bp_3dctf_bin4/`, `bp_3dctf_bin4_ddw/`) rather than flattened into `Tomograms/`. This avoids filename collisions when new processing versions are added, and the folder name acts as the `processing_id`.
- **No `VoxelSpacing{N}/` subfolder.** Voxel binning is recorded directly in `acquisition.toml` (as `voxel_bin` on each `[[tomogram]]` entry); the absolute voxel spacing in Ångström is read from the MRC header by the catalog scanner. Keeping voxel info out of the path avoids duplicating information that lives in the file itself.

Simulation data uses a parallel structure with domain-appropriate folder names. Both share the same schema, which is what makes cross-comparison possible.

---

## Metadata files

### `sample.toml` — sample-level conditions

One file per sample, placed at the root of the sample directory. Contains only what was imaged or simulated — not how. The sample directory name *is* the sample's identity, so `sample.id` is omitted from the file.

### `acquisition.toml` — per-acquisition parameters + processing log

One file per acquisition, placed at the root of each acquisition directory. It contains:

1. Researcher-authored imaging parameters not available from MDOC files (nominal resolution, nominal tilt spacing, target defocus range, energy filter model, phase plate, microscope model).
2. A **processing log**: `[[tomogram]]` and `[[annotation]]` entries appended over time as processing produces new outputs.

The acquisition directory name *is* the acquisition's identity, so `acquisition.id` is omitted from the file.

---

## Schema rules

### Required fields

Only two fields are required for all entries: `sample.data_source` and `sample.project`. All other fields are optional, allowing the schema to grow as researcher needs settle. These two fields are also the only enums — all other fields are open text, with the potential to be tightened into enums later based on how researchers use them.

### Folder naming rules

Four folder names become primary keys in the portal database: the sample directory (`sample_id`), each acquisition directory (`acquisition_id`), each tomogram processing subfolder (`tomogram_id`), and each annotation subfolder (`annotation_id`). The same strings may also be used in path expressions, URLs, and shell commands, so they are restricted to a conservative, cross-platform-safe allowlist.

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

# Raw reconstruction
[[tomogram]]
id                     = "bp_3dctf_bin4"
voxel_bin              = 4
derived_from           = []

# Denoised version derived from the raw
[[tomogram]]
id                     = "bp_3dctf_bin4_ddw"
voxel_bin              = 4
derived_from           = ["bp_3dctf_bin4"]

# Segmentation run on the denoised tomogram
[[annotation]]
id              = "membrain_seg_v10"
type            = "membrane_segmentation"
target_tomogram = "bp_3dctf_bin4_ddw"
```

---

## Researcher workflow: creating metadata

### 0. (Optional) Set up VSCode for live TOML validation

Authoring TOML in **VSCode** with the [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) extension gives you in-editor type checking, enum suggestions, and field hints as you fill in the templates. The `#:schema` directive at the top of each template points the extension at `cryoet_schema/schema.json` (for `sample.toml`) and `cryoet_schema/acquisition.schema.json` (for `acquisition.toml`).

Skipping the editor setup is fine — `pixi run validate {sample_dir}` (step 5) catches the same errors at the end.

### 1. Lay out the sample directory

Copy the starter directory `templates/sample_name/` into the `data/` directory. The starter directory contains empty directories to scaffold the correct directory structure. Then follow the naming instructions below.

Replace `sample_name` with the desired sample id.

```
gouauxlab_20250418_AMmilled29-2/
```

Inside, make a copy of `acquistion_name`. Then update one of the directories to the desired acquistion id for your first acquisition. Repeat this process every time you want to add a new acquisition.

```
gouauxlab_20250418_AMmilled29-2/
  Position_86/
  Position_87/
```

### 2. Fill out `sample_name/sample.toml`

- Complete as many fields marked `<FILL IN>` as you can. For now, the only required fields are `sample.data_source` and `sample.project`.
- Delete the `[synapse]` block if your project is `chromatin`, or vice versa.
- Optionally, uncomment and complete the `[[aunp]]`, `[freezing]`, and `[milling]` blocks.

### 3. Fill out `sample_name/acquistion_name/acquisition.toml` in each acquisition directory

- Complete as many fields marked `<FILL IN>` as you can. For now, no fields are required.

### 4. Append to the processing log as outputs are produced

Each `acquisition.toml` grows over time. For each new output — a new tomogram reconstruction, a denoised version, a segmentation, an STA result — append a new `[[tomogram]]` or `[[annotation]]` entry to the relevant acquisition's file.

**Rules:**
- Do **not** delete or modify a tomogram or annotation entry once added. Reprocessing produces a **new** entry with a new `id`, placed at the bottom of the file.
- The `id` must match one folder name under either `Reconstructions/Tomograms/` or `Reconstructions/Annotations/`.
- Use `derived_from` and `target_tomogram` to record lineage (see above).

### 5. Validate

```
pixi run validate {sample_dir}
```

This validates `sample.toml` and every `acquisition.toml` under the sample directory and will notify the researcher of any fields that violate the schema. Validation will also run during database ingestion — see `cryoet_schema/schema_info.md` for the full list of fields that will be stored, including those auto-derived from MDOCs, MRC headers, OME-Zarr metadata, and directory structure.

---

## Example: mapping Gouaux lab data to this structure

```
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
