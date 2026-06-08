# Plan: Landing-page "Total data" card = true on-disk data size

**Date:** 2026-06-05
**Status:** Ready for implementation
**Author:** planning session (Claude)

## Summary

The landing page already renders a **"Total data"** stat card, but its value is a
large *undercount*: it sums only `PostProcessedTomogram.size_bytes`, and that field
is only ever set to the size of the **first `.mrc` file** of each post-processed
tomogram (`assembler.py:337`). It ignores raw tomograms, frames, MDOCs, OME-Zarr
stores, annotations, gain references, and every MRC after the first.

This plan makes the card report the **true total bytes on disk** by mirroring the
prototype repo `aicryoet-tools`, which computes a per-"lab" `total_size_bytes`
via a recursive `os.scandir` walk and caches it in SQLite; its dashboard's "Total
Data" card is the `SUM` of those.

In `cryoet-ai` the analogous unit is the **sample** (each sample is a top-level
directory under `CATALOG_DATA_ROOT`; `discovery.iter_samples` yields direct children
of the root containing `sample.toml`). We add a per-sample `disk_size_bytes` column,
populate it during scanning with a recursive walk, and change the stats API to sum
it grouped by project. The frontend needs **no functional change** — `StatsBanner`
already sums `size_bytes` across `by_project`.

## Decisions already made

- **Size source: TRUE RECURSIVE ON-DISK SIZE.** Sum *all* bytes under each sample
  directory (frames, raw + post tomograms, zarr, mdoc, annotations, gain refs,
  everything), not just cataloged files.
- **Storage unit: per-sample** (`SampleORM.disk_size_bytes`). Keeps the existing
  per-project rollup and the frontend working unchanged — the stats API just sums a
  different column.
- **Reference implementation:** `/opt/aicryoet-tools/src/aicryoet_tools/catalog/_helpers.py::_dir_size`
  (`os.scandir`, `follow_symlinks=False`, swallow `PermissionError`).

## Findings from investigation (ground truth in the codebase)

- **Schema bootstrap is `create_all`, not Alembic yet.** `cryoet_catalog/db.py::init_schema`
  calls `Base.metadata.create_all(engine)`. Alembic is wired up (`cryoet_catalog/migrations/`)
  but `versions/` is **empty** — migrations are explicitly deferred until production.
  => Fresh DBs (including every test DB) pick up a new ORM column automatically. Only
  *pre-existing* on-disk DBs need a manual `ALTER TABLE`.
- **Drift test will fail unless we carve out the new column.** `tests/cryoet_catalog/test_orm_drift.py`
  asserts every `SampleORM` column maps to a `cryoet_schema` Pydantic field, *except*
  those listed in `db_only_columns`. Current carve-out for `Sample`/`SampleORM` is
  `{"deleted_at"}`. We must add `disk_size_bytes` to that set (it is DB-only; it is
  **not** added to `cryoet_schema.schema.Sample`).
- **`deleted_at` is the exact precedent for a DB-only sample column.** It lives only
  on `SampleORM`, is carved out of the drift test, and is written by explicitly
  injecting it into `sample_payload` before `session.merge` in
  `persistence.upsert_sample_record` (lines 162–165). `disk_size_bytes` should follow
  the same pattern.
- **`_filter_to_columns` (persistence.py:63)** drops payload keys that aren't ORM
  columns, so adding `disk_size_bytes` to the payload dict is safe and will be
  written once it's a real column.
- **Scanner orchestration** (`cryoet_catalog/scanner.py`):
  - `scan_root` loops `discovery.iter_samples(root)` → `_scan_one_sample`.
  - `_scan_one_sample` does mtime gating on **parse-target files**
    (`discovery.parse_targets_for_sample`); if nothing changed and the sample isn't
    soft-deleted and the parse-target set is unchanged, it `skipped += 1` and returns
    *without* re-assembling/persisting. `force=True` bypasses the gate.
  - On the non-skip path it calls `assembler.assemble_sample(sample_loc)` then
    `persistence.upsert_sample_record(...)` inside one transaction. `sample_loc.path`
    is the absolute sample directory — exactly what we walk.
  - **Gating implication:** `disk_size_bytes` will only refresh when a sample is
    re-upserted (i.e., a parse-target changed) or under `force=True`. A change to a
    non-parse-target file (e.g. an extra frame that isn't the representative frame)
    won't trigger a recompute, so the size can go slightly stale until the next
    `--force` scan. This matches `aicryoet-tools`' behavior (manual rescan) and is an
    accepted limitation (see Open Questions).
- **Stats endpoint** (`cryoet_catalog/api/routes/stats.py:143-157`) currently computes
  `size_by_project` by summing `PostProcessedTomogramORM.size_bytes` joined to live
  samples. We replace it with a sum over `SampleORM.disk_size_bytes`. Response shape
  (`StatsOverviewOut` / `ProjectStatRow.size_bytes`) is **unchanged**.
- **Frontend** (`frontend/src/components/landing/StatsBanner.tsx:41`) already does
  `by_project.reduce((sum, p) => sum + (p.size_bytes ?? 0), 0)`. No code change
  required for correctness.
- **`discovery.py` is pure path/metadata ops** ("No file *contents* are read here —
  only directory entries and suffixes"). A `_dir_size` that reads `entry.stat()`
  metadata (not contents) fits this module's contract.

## Goals

1. Landing page "Total data" card reflects true bytes on disk across all live samples.
2. Per-project `size_bytes` in `/stats/overview` reflects true on-disk size per project.
3. No change to the API response shape or the frontend data flow.
4. Tests updated to reflect the new size source; drift test kept green.

## Non-goals

- Computing physical (block-allocated) size vs. logical size — we use `st_size`
  (logical), matching `aicryoet-tools`.
- Following symlinks (we mirror `follow_symlinks=False`).
- Real-time/per-page filesystem walks (size is cached at scan time).
- Per-file-type size breakdowns in the DB.

## Implementation steps

### Step 1 — ORM: add `disk_size_bytes` to `SampleORM`

File: `cryoet_catalog/orm.py` (in `SampleORM`, near `deleted_at`, ~line 56).

```python
# DB-only: total recursive on-disk size of the sample directory in bytes,
# computed by the scanner via discovery.dir_size_bytes(). NULL until first
# scanned. Summed per-project by GET /stats/overview.
disk_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

### Step 2 — Drift test carve-out

File: `tests/cryoet_catalog/test_orm_drift.py` (the `MAPPING` table, `Sample` row).

```python
(Sample, orm.SampleORM, {"deleted_at", "disk_size_bytes"}, {"sample_id"}),
```

(Without this, the "ORM column with no Pydantic field" half of the drift test fails.)

### Step 3 — Recursive size helper in `discovery.py`

File: `cryoet_catalog/discovery.py`. Add (ported from `aicryoet-tools`
`_helpers.py::_dir_size`, public-named since the scanner calls it):

```python
import os  # add to imports

def dir_size_bytes(path: Path) -> int:
    """Total logical size (bytes) of everything under ``path``, recursively.

    Mirrors aicryoet-tools' approach: walk with ``os.scandir``, sum
    ``st_size`` of regular files, do NOT follow symlinks, and silently skip
    directories we can't read (``PermissionError`` / ``OSError`` on NFS).
    Counts *all* files on disk — frames, MDOCs, raw + post tomograms, OME-Zarr
    chunks, annotations, gain refs — not just cataloged ones.
    """
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += dir_size_bytes(Path(entry.path))
                except OSError:
                    continue  # entry vanished / unreadable mid-walk
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        pass
    return total
```

Add `dir_size_bytes` to any `__all__` if present (discovery.py currently has none).

### Step 4 — Compute + persist during scan

Two small edits, threading the value through the existing write path (mirrors how
`deleted_at` is injected).

**4a. `persistence.upsert_sample_record`** (`cryoet_catalog/persistence.py:126`):
add a keyword param and inject into `sample_payload` before merge.

```python
def upsert_sample_record(
    session: Session,
    record: SampleRecord,
    *,
    extras: list[ExtrasEntry],
    warnings: list[ScanWarning],
    scan_run_id: str,
    disk_size_bytes: int | None = None,
) -> None:
    ...
    sample_payload = record.sample.model_dump(exclude_none=False)
    sample_payload["deleted_at"] = None
    sample_payload["disk_size_bytes"] = disk_size_bytes   # NEW
    session.merge(
        orm.SampleORM(**_filter_to_columns(sample_payload, orm.SampleORM))
    )
```

Rationale: passing it explicitly and always setting it (like `deleted_at`) avoids
the `session.merge` partial-object ambiguity. Default `None` keeps existing callers
(and tests that call `upsert_sample_record` directly) working.

**4b. `scanner._scan_one_sample`** (`cryoet_catalog/scanner.py:174-197`): compute the
size on the non-skip path only (so skipped samples don't pay the walk cost) and pass
it through.

```python
    # Assemble + persist in one transaction
    with session.begin():
        result = assembler.assemble_sample(sample_loc)
        ...
        if result.record is None:
            ...
            return
        ...
        disk_size = discovery.dir_size_bytes(sample_loc.path)   # NEW
        persistence.upsert_sample_record(
            session,
            result.record,
            extras=result.extras,
            warnings=result.warnings,
            scan_run_id=scan_run_id,
            disk_size_bytes=disk_size,                          # NEW
        )
```

(`discovery` is already imported in `scanner.py`.)

### Step 5 — Stats API: sum the new column

File: `cryoet_catalog/api/routes/stats.py`, replace the `size_by_project` block
(lines 141–157):

```python
    # size_bytes per project — true on-disk size cached per sample by the
    # scanner (discovery.dir_size_bytes). Live samples only.
    size_by_project = dict(session.execute(
        select(
            orm.SampleORM.project,
            func.coalesce(
                func.sum(func.coalesce(orm.SampleORM.disk_size_bytes, 0)), 0
            ),
        )
        .where(orm.SampleORM.deleted_at.is_(None))
        .group_by(orm.SampleORM.project)
    ).all())
```

No change to `ProjectStatRow` construction (line 169 already does
`size_bytes=int(size_by_project.get(p, 0) or 0)`), `StatsOverviewOut`, or
`api/schemas.py`.

### Step 6 — Frontend (optional, no functional change)

`StatsBanner.tsx` already works. **Optionally** relabel for clarity
(`StatsBanner.tsx:44`): `{ label: 'Total data', value: ... }` →
`{ label: 'Total data on disk', value: ... }`. Mark as optional/cosmetic; confirm
with the user before changing copy.

### Step 7 — Migration path for existing on-disk DBs

- **New / test DBs:** no action — `create_all` includes the new column.

## Tests

### Update: `tests/cryoet_catalog/test_api_stats.py`
The `seeded_client` fixture currently encodes expected `size_bytes` via
`PostProcessedTomogramORM.size_bytes`. After the change, `by_project.size_bytes`
comes from `SampleORM.disk_size_bytes`. Edits:
- Seed `disk_size_bytes=<n>` on each `SampleORM(...)` (e.g. `chrom_a=6000`,
  `chrom_b=0`/NULL, `syn_a=5000`, `syn_b=0`, `dead=99999`).
- Update assertions in `test_by_project_rows_match_seeded_counts`,
  `test_soft_deleted_excluded_from_by_project`, `test_null_size_bytes_contributes_zero`
  to reference the sample-level sizes. Keep the same numeric expectations (6000 /
  5000 / soft-deleted excluded / NULL→0) so the intent of each test is preserved;
  the tomogram `size_bytes` seeds become irrelevant to these assertions.
- `test_totals_*` and empty-DB tests are unaffected.

### Update: `tests/cryoet_catalog/test_orm_drift.py`
Carve-out edit from Step 2 (the test itself enforces this).

### New: `tests/cryoet_catalog/test_discovery.py`
Add `dir_size_bytes` unit tests:
- Empty dir → `0`.
- Flat files (`a`+`b` of known sizes) → sum.
- Nested subdirs (incl. a `.zarr/`-like dir with chunk files) → recursive sum.
- A broken symlink and a symlink to a large file → not followed (counts symlink
  entry only / skips). Assert it doesn't raise and doesn't inflate the total.
- Non-existent path → `0` (no raise).

### New / update: `tests/cryoet_catalog/test_scanner.py` (and/or `test_persistence.py`)
- After scanning a fixture sample tree, assert `SampleORM.disk_size_bytes` is
  populated and equals `discovery.dir_size_bytes(sample_dir)`.
- Assert a skipped (gated) sample retains its previously-stored `disk_size_bytes`
  (i.e., the skip path doesn't null it).
- Assert `force=True` recomputes after adding a file.
- `test_persistence.py`: assert `upsert_sample_record(..., disk_size_bytes=N)` writes
  `N`, and the default (omitted) writes NULL.

### Run
```
pixi run -e catalog pytest tests/cryoet_catalog/test_discovery.py \
  tests/cryoet_catalog/test_api_stats.py tests/cryoet_catalog/test_orm_drift.py \
  tests/cryoet_catalog/test_scanner.py tests/cryoet_catalog/test_persistence.py
```
(Confirm the exact pixi env/command from the repo's test conventions before running.)

## Risks & mitigations

- **Stale size when only non-parse-target files change** (gating). Mitigation:
  documented; `--force` recomputes. Matches reference project. (See Open Questions for
  an alternative.)
- **Walk cost on large samples.** Only paid on the upsert path (changed samples), not
  on skips, and not per page load. Acceptable; same model as `aicryoet-tools`.
- **NFS permission / transient errors.** Handled by swallowing `OSError` /
  `PermissionError` per-entry (won't abort a scan).
- **Symlinked frames undercount.** `follow_symlinks=False` means symlinked large
  files count as the link, not the target. Deliberate (mirrors reference). Flag for
  user if their data symlinks bulk data.
- **`session.merge` overwriting `disk_size_bytes` to NULL** if not passed. Mitigated
  by always injecting it in `sample_payload` (Step 4a), exactly like `deleted_at`.

## Open questions

1. **Stale-size tolerance.** Accept "refresh on parse-target change or `--force`"
   (this plan), or always recompute `dir_size_bytes` on every scan regardless of
   gating (more accurate, more I/O — would mean moving the walk above the skip
   `return` in `_scan_one_sample`, or doing a lightweight size-only UPDATE on the
   skip path)? Recommendation: ship the gated version; revisit if staleness bites.
2. **Symlink handling.** Keep `follow_symlinks=False` (reference behavior) or follow
   symlinks because bulk frames/tomograms are symlinked at Janelia? Needs a quick
   check of how the real data root is laid out.
3. **Label copy.** Rename card to "Total data on disk" (Step 6) or leave as
   "Total data"? Cosmetic — confirm with user.
