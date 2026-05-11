# Dashboard MVP — port aicryoet-tools functionality to the catalog portal

**Date:** 2026-05-08
**Author:** allison-truhlar (planning via Claude)
**Target branch:** `dev`

## 1. Context

`aicryoet-tools/` ships a NiceGUI Python dashboard (port 8082) that browses cryoET acquisitions, tomograms, and MD trajectories pulled from a project-specific SQLite index (`.portal_index.db`). It has rich features: filterable splitter UI, embedded Neuroglancer viewers, MRC center-slice previews, MDOC tilt-angle polar plots, and OVITO-rendered MD trajectory previews.

`/cryoet-ai` (this repo) is the new home for the same end-user experience built against `cryoet_catalog`'s SQLite DB and FastAPI read API, with a TanStack Start + Material UI frontend already scaffolded:

- Backend: FastAPI app at `cryoet_catalog/api/`, routes `/samples`, `/samples/{id}`, `/samples/{id}/warnings`, `/scans`, `/extras`. Read-only.
- Frontend: TanStack Start + React 19 + MUI 6 in `frontend/`, currently a single `/samples` route showing a plain HTML table.
- DB schema: `samples` + side tables (`chromatin`, `synapse`, `simulation`, `freezing`, `milling`, `aunp`), `acquisitions`, `tomograms`, `annotations`, plus `extras`, `scans`, `scan_warnings`, `scan_state`, `catalog_meta`.

## 2. Scope decisions (settled with user)

1. **MVP = cryoET parity only.** Every cryoET-relevant feature in the source dashboard ships in this MVP: tilt-series cards, MDOC polar plots, tomogram MRC previews, Neuroglancer launches, filter rail + list/detail splitter, summary cards, scan history.
2. **MD / simulation work is deferred.** No simulation data exists in the catalog yet, so MD-specific schema, parsers, endpoints, and UI move to a follow-on (see **§14 — Future steps**). The existing `simulation` side-table is untouched in this MVP. The cryoET filter rail still exposes `data_source` (which already exists on `samples`) so future simulation rows are filterable when they arrive.
3. **Schema grows for cryoET parity only.** The catalog gains a `tilt_series` table and small column additions on `tomograms` and `acquisitions`.
4. **Viewers — full parity (functional, not pixel-faithful).** Tomogram and tilt-series MRC/EER previews + Neuroglancer launches and MDOC polar plots all ship.
5. **Rescan trigger from the UI is dropped.** Rescans are CLI-only via `pixi run scan` (decision §11.13).
6. **UI fidelity — MUI-native.** Replicate the layout intent (filter rail + list/detail splitter + summary cards) using idiomatic MUI components rather than pixel-cloning the Quasar/NiceGUI styles.

## 3. Functionality matrix (source → target)

Every row is **in** the MVP unless noted. The "Backed by" column flags new schema/parser/API/UI work tracked in §5–§9. MD-specific rows from the source dashboard are deferred to §14.

| `aicryoet-tools` feature | Backed by (new in this MVP) |
|---|---|
| Home: per-project summary cards (samples, acquisitions, tomograms, size) | `GET /stats/overview` (§7.3); per-row counts on samples list |
| Home: total stats cards | `GET /stats/overview` |
| Home: rescan / full rescan buttons | **Out of MVP.** Operators rescan via the existing CLI (`pixi run scan`); the home page shows last-scan status and links to `/scans` instead (§11.13). |
| CryoET filter: project, sample, voltage, microscope, camera, pixel-spacing range, n_tilts range, voxel-size range, has_tomograms, image_format | Extended `GET /samples` + `GET /filters/options` (§7.1, §7.2). `n_tilts` / `image_format` come from new `tilt_series` table (§5) |
| CryoET list/detail splitter with row-click selection + arrow-key nav | `SamplesTable` (§9.5) |
| Acquisition path with copy / "open in file browser" | Copy button only; file-browser button needs a path field on `acquisitions` (added §5.2) |
| Per-tilt-series cards (polar plot, center-tilt preview, Neuroglancer button) | New `tilt_series` table (§5), MDOC parser (§6.1), `GET /tilt-series/.../preview.png` + `.../polar.png` + `POST .../neuroglancer` (§7.4–§7.5), `TiltSeriesCard` (§9.5) |
| Per-tomogram cards: metadata, MRC center-slice preview, Neuroglancer button | `GET /tomograms/.../preview.png` + `POST .../neuroglancer` (§7.4–§7.5) |
| Annotations list | Existing `annotations` table |
| Lightbox/fullscreen image viewer | `Lightbox` component (§9.2) |
| Scan warnings | `scan_warnings` (existing) — surface on sample detail and on home page (warning count chip) |
| Scan history view | `GET /scans` + new `/scans` route (§9.7); manual refresh only (decision §11.21) |
| MD page (simulation list, REMD detail, scatter preview, dump groupings, info dialog) | **Deferred to §14.** No simulation data exists yet. |

## 4. Architecture

```
frontend/  (TanStack Start, MUI, port 3000, SSR + hydrate)
   │
   │  /api proxy already wired in vite.config.ts (dev); SSR loaders hit
   │  CRYOET_API_BASE_URL (default http://localhost:8000) directly
   ▼
cryoet_catalog.api  (FastAPI, port 8000)   [READ-ONLY]
   • read endpoints (samples, scans, warnings, extras, filters, stats)
   • image rendering (tomogram + tilt-series previews, polar plots)
   • Neuroglancer launches (in-process server, single uvicorn worker)
   │
   ▼
cryoet_catalog.db   (SQLite via SQLAlchemy; Alembic-managed migrations)
   ▲
   │ writes
cryoet_catalog scanner   (CLI only — `pixi run scan`; no API write path)
   • scanner.py + sibling modules: discovery.py, assembler.py,
     persistence.py, state.py
   • parsers/ subpackage (TOML, MDOC, MRC header, OME-Zarr)
```

Note: `scanner.py` is a top-level module under `cryoet_catalog/`, not a package — `discovery.py`, `assembler.py`, `persistence.py`, `state.py`, and the `parsers/` subpackage are all siblings of it, directly under `cryoet_catalog/`.

The scanner remains the single writer to the DB and is invoked exclusively via the CLI for MVP — the API has no write endpoints (decision §11.13). MRC/EER/Neuroglancer helpers are function-extracted into `cryoet_catalog/imaging/` rather than depending on `aicryoet-tools` (decision §11.6). All matplotlib rendering (polar plots) uses the **object-oriented API** (`Figure(); FigureCanvasAgg(fig)`) — never `pyplot` — so concurrent renders on the threadpool don't corrupt each other (§7.5).

**New runtime dependencies** (§11.5): `numpy`, `matplotlib-base`, `Pillow`, `neuroglancer`, `zarr`, `tifffile`, `eerfile`. These land in `feature.api.dependencies` in `pixi.toml` (`matplotlib-base` rather than `matplotlib` to avoid pulling Qt). `eerfile` is verified for channel availability before Phase 3; if PyPI-only it goes under `feature.api.pypi-dependencies`. The decision to vendor still saves us from pulling `napari`, `nicegui`, `pyqt6`/`pyside6`, and `ovito`.

## 5. Schema additions

All schema changes happen up-front — every API and UI feature below depends on them.

### 5.1 New tables

**`tilt_series`** — one row per tilt series, FK on an acquisition.
- PK: `(sample_id, acquisition_id, tilt_series_id)` — `tilt_series_id` is a string id derived from the MDOC stem so reruns dedupe.
- `mdoc_path: str | None`, `st_path: str | None`, `zarr_path: str | None`.
- `n_tilts: int | None`, `tilt_range_min: float | None`, `tilt_range_max: float | None`, `tilt_axis_angle: float | None`.
- `voltage: float | None`, `pixel_spacing: float | None`, `image_format: enum('EER','TIFF','MRC') | None`, `microscope: str | None`, `camera: str | None`.
- `tilt_angles: list[float] | None` (JSON column) — full per-image angles list, used by the polar plot endpoint without re-parsing the MDOC.
- `mtime: float`.

**Soft-delete behavior** (decision §11.22): `tilt_series` rows are **left untouched** when a sample is soft-deleted, matching the existing convention for `acquisitions` / `tomograms` / `annotations` / `aunp` / sub-tables / `extras` / `scan_warnings` / `scan_state` (see `cryoet_catalog/persistence.py:317-320` — "Child entities ... are intentionally NOT touched: soft delete preserves history so a sample can be resurrected by a later upsert"). Resurrection via re-upsert handles re-creation in the same way it does for the existing child tables. The outer `samples.deleted_at IS NULL` filter on every API query already prevents orphaned rows from leaking into results, so no cascade is required for correctness.

### 5.2 Existing tables — column additions

**`tomograms`** — add `size_bytes: int | None`. Required for tomogram cards and home-page size stats; recorded by the scanner via `os.stat(mrc_path).st_size`.

**`acquisitions`** — add `path: str | None` (filesystem directory) so the detail panel can render copy-path and "open in file browser" buttons. The scanner records the directory containing the acquisition's MDOC / first MRC. **Synthesized acquisitions** (assembler step 1.5, for filesystem-only acquisitions with no `acquisition.toml`) get this set to the directory the scanner walked.

### 5.3 Pydantic + JSON Schema

Extend `cryoet_schema.schema` with a `TiltSeries` record and add `tomograms.size_bytes` / `acquisitions.path` to existing models. Regenerate `cryoet_schema/schema.json` and `acquisition.schema.json` via the existing `json-schema` task.

The `Simulation` Pydantic model is **untouched** in this MVP — see §14 for the deferred extension.

### 5.4 Migrations — Alembic

`Base.metadata.create_all(engine)` cannot add columns, alter constraints, or rename anything on an existing DB. Pre-MVP DBs already exist on developer machines; we adopt **Alembic** so schema evolution is repeatable and reviewable from this point forward.

- Add `alembic` to `feature.catalog.dependencies` in `pixi.toml`.
- Initialize Alembic at `cryoet_catalog/migrations/` with `env.py` reading `CATALOG_DB_URL` (and falling back to `DEFAULT_DB_URL` from `db.py`). Use `render_as_batch=True` for SQLite-safe ALTERs.
- First revision (`0001_initial.py`): autogenerate against the *current* (pre-MVP) ORM. Lock this revision in **before** any ORM changes for §5.1/§5.2 land, so the baseline is stable. Capture the exact table set produced by `0001` as a frozen `BASELINE_TABLES` constant in `cryoet_catalog/db.py` — this is the fingerprint used by `init_schema` (below) to decide whether a legacy DB is safe to stamp. Existing developer DBs whose shape matches the `0001` baseline get **`alembic stamp 0001`** (NOT `stamp head`) followed by `upgrade head`; mismatched dev DBs get re-created from a fresh scan (documented in `migrations/README.md` as the "if your dev DB is older than `0001`, re-scan to rebuild it" path).
- Second revision (`0002_dashboard_mvp.py`): the MVP delta — adds `tomograms.size_bytes`, `acquisitions.path`, and the new `tilt_series` table.
- New `pixi run migrate` task = `alembic upgrade head` (lives under `feature.catalog.tasks` alongside `scan`). New `pixi run migrate-revision -- "<message>"` task = `alembic revision --autogenerate -m "<message>"` (researchers should never hand-author revisions).
- `init_schema` is **rewritten** so `create_all` is no longer the entry point. The new logic:
  1. If the `alembic_version` table exists → `command.upgrade(cfg, "head")`.
  2. Else if any ORM table exists (legacy DB):
     - **Fingerprint check first**: collect `set(inspect(engine).get_table_names())` and compare against `BASELINE_TABLES`. If the sets are not equal (extra tables, missing tables, or both), refuse to stamp and raise a clear error directing the user to wipe and re-scan (`"DB schema does not match the 0001 baseline (missing: …, extra: …). Re-create the DB via 'pixi run scan' against your data root; see cryoet_catalog/migrations/README.md."`).
     - On match: `command.stamp(cfg, "0001")` then `command.upgrade(cfg, "head")`. Stamping at the baseline revision id (not `"head"`) means the subsequent upgrade actually runs `0002` and every later revision; stamping at `"head"` would mark the DB as up-to-date and silently skip every pending migration.
  3. Else (fresh DB) → `command.upgrade(cfg, "head")` from empty.
  This eliminates the "create_all + upgrade head" double-application bug. `create_all` is removed from the lifecycle entirely once Alembic is in.
- Update `tests/cryoet_catalog/test_orm_drift.py` to cover the new columns. New `tests/cryoet_catalog/test_alembic.py`:
  - autogenerate diff against ORM is empty at head;
  - round-trip `upgrade head` then `downgrade -1` then `upgrade head` on an empty SQLite;
  - seed a pre-MVP DB fixture, run `upgrade head`, assert the new columns exist and pre-existing rows survive (with row-count checks per affected table to catch `render_as_batch` data loss);
  - **DDL-drift sanity**: `create_all(empty_engine)` produces the same table set as `upgrade head` from empty (catches forgotten revisions when ORM is changed).
- New `tests/cryoet_catalog/test_init_schema.py` covers the four `init_schema` branches end-to-end:
  - **empty**: fresh SQLite → `init_schema` → assert `alembic_version` row equals head and the full head table set exists.
  - **clean-baseline (legacy)**: seed a SQLite with exactly `BASELINE_TABLES` (no `alembic_version`) → `init_schema` → assert it stamped at `0001`, then upgraded to head, and the new MVP columns/tables are present. Seed a row in each pre-existing affected table beforehand and assert the row survives.
  - **stamped-and-current**: SQLite already at head with `alembic_version` set → `init_schema` is a no-op (no errors, version unchanged, table set unchanged).
  - **mismatched-shape**: seed a SQLite that has *some but not all* of `BASELINE_TABLES` (and/or an extra unrelated table) → `init_schema` raises the fingerprint-mismatch error and does NOT stamp or alter the DB. Assert the DB is unchanged after the failed call (no `alembic_version` table appeared, no new MVP tables were created).

SQLite-specific caveats to document in `migrations/README.md`: batch mode is mandatory for `ALTER TABLE`; batch mode rebuilds tables, dropping manual indexes/PRAGMAs; autogenerate misses CHECK constraint changes and some default changes — review every revision diff before committing.

## 6. Scanner / parser additions (`cryoet_catalog/`)

### 6.1 Tilt-series parsing

- Extend `discovery.py` to enumerate MDOC files alongside MRC tomograms when walking an acquisition directory. Discovery stays content-blind: it records that *an MDOC exists at this path*, nothing more (preserves the discovery/assembler split).
- Extend `parsers/mdoc.py` to **also return the per-image `tilt_angles: list[float]`** (today it's computed for min/max only and dropped at parsers/mdoc.py:144). The polar-plot endpoint depends on it. The new key is added to the returned `fields` dict; existing assembler whitelisting (`MDOC_FIELDS` in assembler.py) ignores it, so callers writing into `Acquisition` are unaffected. The new `tilt_series` parser reads the angles directly from `parse_acquisition_mdocs` output rather than routing them through `Acquisition`.
- Add `cryoet_catalog/parsers/tilt_series.py` that wraps `parsers/mdoc.py` and emits `TiltSeriesRecord` rows including the per-image angles list, image_format, and zarr_path.
- `microscope` and `camera` are NOT extracted from the MDOC. Source of truth is `acquisition.toml` only (decision §11.14). The MDOC-keys-as-fallback path is explicitly rejected; if researchers want microscope filters to work, they must populate the TOML. The frame-extension `infer_camera` fallback in `assembler.py` stays for now (camera only).
- Detect `image_format` by sniffing the directory for `*.eer` / `*.tif` / `*.mrc` siblings (port from `aicryoet-tools/src/aicryoet_tools/dashboard/pages/cryoet.py:921`).
- Look for converted Zarr stacks following the same convention as `aicryoet-tools` (`<mdoc-stem>.zarr` next to the MDOC).
- **MDOC-stem collision handling** (decision §11.23): if two MDOCs in the same acquisition produce the same stem, append the parent-dir name (or, if still colliding, a numeric suffix) to make `tilt_series_id` unique, and emit a `tilt_series_id_collision` scan warning. Both tilt series are catalogued — no silent data loss.
- `assembler.py` merges `TiltSeriesRecord` into the `SampleRecord`. `persistence.py` upserts; `state.py` adds the MDOC files to mtime gating. Soft-delete leaves `tilt_series` rows in place — same convention as every other child table (decision §11.22). No new cascade hook is added to `soft_delete_missing_samples`.
- Extend `extras` write path to accept `entity_type='tilt_series'` (decision §11.24): TOML `[[tilt_series]]` sections with unknown keys round-trip through `extras` like acquisitions/tomograms today.

### 6.2 Other column-fill work

- Tomogram size: `os.stat(mrc_path).st_size` at parse time.
- Acquisition path: directory of the acquisition (or the parent of the first MRC file found), recorded once per acquisition. Synthesized acquisitions (no `acquisition.toml`) get the path the scanner walked.

### 6.3 Tests

- Extend the existing `test_parser_mdoc.py` to cover the surfaced `tilt_angles` list.
- New: `test_parser_tilt_series.py` (including a collision-handling case with two MDOCs producing the same stem).
- New: `test_assembler_tilt_series.py` — fixture acquisition dir with MDOC + MRC siblings round-trips through the assembler into a `SampleRecord` with one `tilt_series` row.
- New: `test_persistence_tilt_series_soft_delete.py` — soft-delete a sample, assert its `tilt_series` rows are still present (same convention as `tomograms`/`annotations`); then re-upsert the sample and assert the rows are still reachable through `/samples/{id}`.
- New: `test_extras_tilt_series.py` — TOML with `[[tilt_series]]` extras key round-trips through the extras table.

## 7. Backend API (`cryoet_catalog/api/`)

### 7.1 Extend `GET /samples` filtering

Currently supports `project`, `data_source`, `has_warnings`, `limit`, `offset`. Add:

| Query param | Type | Backed by |
|---|---|---|
| `type` | repeatable str | `samples.type` |
| `microscope` | repeatable str | `acquisitions.microscope` (EXISTS) |
| `voltage` | repeatable float | `acquisitions.voltage` |
| `camera` | repeatable str | `acquisitions.camera` |
| `pixel_size_min` / `pixel_size_max` | float | `acquisitions.pixel_size` (NULL passes) |
| `voxel_spacing_min` / `voxel_spacing_max` | float | `tomograms.voxel_spacing_angstrom` (NULL passes) |
| `n_tilts_min` / `n_tilts_max` | int | `tilt_series.n_tilts` |
| `image_format` | repeatable str | `tilt_series.image_format` |
| `has_tomograms` | bool | EXISTS on `tomograms` |
| `q` | str | LIKE on `sample_id` and `description` |

Per-acquisition / per-tomogram / per-tilt-series filters become `EXISTS` subqueries on the sample list query. NULL-tolerant range filters mirror `aicryoet-tools/.../dashboard/filters.py:344`. Expose `sort` (`sample_id|project|type`) and `order` (`asc|desc`).

`SampleSummary` gains `n_acquisitions`, `n_tomograms`, `n_tilt_series` aggregate counts so the table renders without per-row round-trips. **Counts are total child-row counts intrinsic to the sample, not filtered counts** — a sample with 3 tomograms shows "3" regardless of which range filters are active (decision §11.15). Implemented as correlated subqueries on the SELECT list.

### 7.2 New `GET /filters/options`

```json
{
  "projects": [...],
  "data_sources": [...],
  "types": [...],
  "microscopes": [...],
  "voltages": [200, 300],
  "cameras": [...],
  "image_formats": ["EER", "TIFF", "MRC"],
  "pixel_size":      {"min": 1.0, "max": 4.5},
  "voxel_spacing":   {"min": 4.4, "max": 16.6},
  "n_tilts":         {"min": 41,  "max": 121}
}
```

`SELECT DISTINCT … WHERE … IS NOT NULL ORDER BY …` for categorical; `SELECT MIN(...), MAX(...)` for ranges. New module `cryoet_catalog/api/routes/filters.py`.

Empty facets are returned as empty arrays (or `null`/missing range bounds). The frontend hides the corresponding drawer rows entirely (decision §11.25); URL-schema params remain valid so old shared URLs round-trip.

### 7.3 New `GET /stats/overview`

```json
{
  "totals": {
    "samples": 42,
    "acquisitions": 87,
    "tilt_series": 91,
    "tomograms": 153,
    "annotations": 64,
    "warnings": 11
  },
  "by_project": [
    {"project": "chromatin", "samples": 18, "acquisitions": 32, "tomograms": 70, "size_bytes": 1234567890}
  ]
}
```

`size_bytes` aggregation uses the new `tomograms.size_bytes` column (§5.2).

### 7.4 Tomogram preview + Neuroglancer

`GET /tomograms/{sample_id}/{acquisition_id}/{tomogram_id}/preview.png`
- Look up the tomogram row, read `mrc_path` (fall back to `zarr_path`).
- **Validate the resolved path is under `app.state.data_root_resolved`** (decision §11.16) — `Path.resolve(strict=True)` then `is_relative_to` against the once-at-startup resolved data root; 404 if not.
- Render center XY slice with 1–99% percentile contrast at 1200 px wide, encoded as PNG.
- `Cache-Control: public, max-age=3600` and an `ETag` based on file mtime.
- 404 if the row is missing, 422 if the file is missing on disk.
- Implementation: function-extracted into `cryoet_catalog/imaging/_mrc.py` (no module-level dep on `aicryoet-tools`). Heavy work runs on `fastapi.concurrency.run_in_threadpool`. LRU cache keyed on `(mrc_path, mtime)`.

`POST /tomograms/{sample_id}/{acquisition_id}/{tomogram_id}/neuroglancer`
- Loads the volume in a worker thread; calls the function-extracted `view_neuroglancer(...)` in `cryoet_catalog/imaging/_neuroglancer.py` (see §11.6). Bound to `NEUROGLANCER_BIND_ADDRESS` (default `0.0.0.0`).
- Returns `{ "url": "http://hostname:port/...#!{...}" }`. The frontend rewrites the hostname to `window.location.hostname` before opening (matches `aicryoet-tools/.../pages/cryoet.py:1166`).
- **Bounded viewer registry**: an `OrderedDict` LRU at `app.state.active_viewers` capped by `NEUROGLANCER_MAX_VIEWERS` (default `8`), guarded by an `asyncio.Lock` so concurrent launches don't double-evict. Eviction means **dropping the registry's reference** to the viewer; the underlying `neuroglancer.Viewer` object has no per-instance `.stop()` — `neuroglancer.stop()` is process-global and is not called here. Document in the route module: "evicting a viewer means new launches replace the slot; the underlying viewer may linger in process memory until GC. Restart the API to fully reset Neuroglancer state."
- Wrap the launch in `run_in_threadpool` — Neuroglancer's startup blocks for tens of ms and shouldn't run on the event loop.
- Document `--no-reload` requirement: Neuroglancer binds an HTTP server once per process; under `--reload` the second launch fails. Lifespan logs a loud warning if `UVICORN_WORKERS` (or equivalent env signal) reports >1 worker.

### 7.5 Tilt-series preview + polar + Neuroglancer

`GET /tilt-series/{sample_id}/{acquisition_id}/{tilt_series_id}/preview.png`
- Median-angle tilt image. Mirrors `_render_center_tilt` in `aicryoet-tools/.../pages/cryoet.py:866`. Prefer `zarr_path`; otherwise read EER/TIFF/MRC via the function-extracted `cryoet_catalog/imaging/_tilt_image.py` (see §11.6). Path-validated against `app.state.data_root_resolved`.

`GET /tilt-series/{...}/polar.png`
- Semicircular polar plot of the cached `tilt_angles`. Port `_render_tilt_angle_plot` (cryoet.py:567) verbatim, but rewritten on the **matplotlib OO API** (`Figure(); FigureCanvasAgg`) — never `pyplot` — so concurrent threadpool renders don't share global state.
- **Cache key = `(tilt_series PK, mtime_of_mdoc, POLAR_RENDER_VERSION)`** — mtime guards against re-acquisitions; `POLAR_RENDER_VERSION` is a module constant bumped manually whenever the renderer changes, so renderer updates invalidate the cache without needing per-file changes.

`POST /tilt-series/{...}/neuroglancer`
- Launches a Neuroglancer viewer for the tilt stack (zarr-preferred lazy-loading path from cryoet.py:641). Returns `{ url }`. Shares the bounded viewer registry (with its lock) and threadpool launch from §7.4. Same single-worker caveat.

### 7.6 Scan history (read-only)

`GET /scans` and `GET /scans/{scan_run_id}` — already partially exposed; confirm both are wired and return started_at, ended_at, root, status, upserted/skipped/failed counts.

The `/scans` page is **manual-refresh only** (decision §11.21). No polling, no SSE. A running scan is reflected on the next page load. The home page's "Last scan" inline shows the most recent row's `ended_at` and status, refreshed on navigation.

**`POST /scans/rescan` is out of MVP** (decision §11.13). Operators rescan via the existing CLI (`pixi run scan`). This drops the BackgroundTasks vs. asyncio-vs-process-pool decision from MVP scope, eliminates the 409-race concern, and keeps the scanner's "single-writer contract" trivially honored.

### 7.7 Routes file layout

```
cryoet_catalog/api/routes/
    samples.py        (extended)
    scans.py          (read-only: GET /scans, GET /scans/{id})
    warnings.py       (unchanged)
    extras.py         (unchanged)
    filters.py        (NEW)
    stats.py          (NEW)
    tomograms.py      (NEW — preview + neuroglancer)
    tilt_series.py    (NEW — preview + polar + neuroglancer)
```

Wire them in `cryoet_catalog/api/main.py`.

### 7.8 Schema additions (`api/schemas.py`)

- `FiltersOptionsOut`, `StatsOverviewOut`, `ProjectStatRow`, `ViewerLaunchOut`.
- `TiltSeriesOut`.
- **Decision: typed Pydantic per sub-entity** (decision §11.18). Each existing side-table (`chromatin`, `synapse`, `simulation`, `freezing`, `milling`, `aunp`) gets its own Pydantic class with explicit fields; `SampleDetail.simulation: SimulationOut | None`, `.chromatin: ChromatinOut | None`, etc. No `dict[str, Any]` anywhere on the wire. The frontend's `frontend/src/api/types.ts` mirrors these field-by-field. `SimulationOut` matches the existing `Simulation` Pydantic model shape — no MD-specific fields are added in this MVP (§14).

### 7.9 Tests (`tests/cryoet_catalog/`)

- `test_api_filters.py`: each new query param narrows the result set as expected; range filters preserve NULLs.
- `test_api_filters_options.py`: option lists are sorted and unique; empty facets return empty arrays.
- `test_api_stats.py`: counts agree with the seeded fixture DB.
- `test_api_tomograms_preview.py`: 200 + `image/png` for a fixture MRC; 404 for unknown id; 422 for missing file.
- `test_api_tilt_series.py`: preview + polar + neuroglancer endpoints against a fixture MDOC.
- `test_api_neuroglancer.py`: smoke test, marked `slow`. Bounded-LRU eviction also covered here, including a concurrent-launch race test (two `asyncio.gather`'d launches when at capacity should not crash).
- `test_api_path_validation.py`: previews for paths outside `CATALOG_DATA_ROOT` return 404; symlink traversal is also rejected (`Path.resolve()` chase). Document Zarr internal-symlink caveat (covered in §11.16) but don't gate MVP on it.
- Seed fixtures via the existing test-DB pattern (`app.state.engine` pre-seeded).

## 8. Configuration

| Var | Purpose | Default |
|---|---|---|
| `CATALOG_DB_URL` | SQLAlchemy URL | `sqlite:///cryoet_catalog.db` (existing) |
| `CORS_ORIGINS` | Allowed origins | `http://localhost:5173` (existing) |
| `CATALOG_DATA_ROOT` | Filesystem root that bounds all preview/Neuroglancer reads | **required**; API refuses to start without it |
| `CRYOET_API_BASE_URL` | Base URL the frontend's SSR loaders use to reach the API | `http://localhost:8000` |
| `NEUROGLANCER_BIND_ADDRESS` | Bind address for Neuroglancer servers | `0.0.0.0` |
| `NEUROGLANCER_MAX_VIEWERS` | LRU size for active Neuroglancer viewers (oldest evicted on overflow) | `8` |
| `PREVIEW_CACHE_MAX_ENTRIES` | LRU size for rendered PNGs | `64` |

`CATALOG_DATA_ROOT` is enforced in two places: (1) FastAPI lifespan refuses to start if unset or non-existent, and **resolves the path once** via `Path.resolve(strict=True)` into `app.state.data_root_resolved`; (2) every preview / Neuroglancer route resolves the DB-recorded path (`Path.resolve(strict=True)`) and 404s if the result isn't `is_relative_to(app.state.data_root_resolved)`. This is defense-in-depth for the API/scanner-different-host case (HHMI norm) and also blocks symlink-traversal escapes (decision §11.16).

`CRYOET_API_BASE_URL` is read by the frontend's SSR runtime (Node `process.env`). The Vite dev proxy in `vite.config.ts` is dev-only — production deployments need a reverse proxy (nginx/Caddy) routing `/api/*` to the FastAPI backend. Document both in the README "Running the app" section.

Add a "Running the app" section to `README.md` documenting all six vars, plus the **`--workers 1 --no-reload`** uvicorn requirement (Neuroglancer's HTTP server binds once per process; multi-worker or autoreload breaks viewer launches — decision §11.9). Lifespan logs a loud warning at startup if it can detect >1 worker.

## 9. Frontend (`frontend/src/`)

### 9.1 Routes

| Route | New? | Purpose |
|---|---|---|
| `/` | rewrite | Home: project summary cards + total stats + browse links + last-scan inline status |
| `/samples` | rewrite | CryoET browser: filter rail + samples table + detail panel |
| `/samples/$sampleId` | new (nested) | Same page, detail panel pre-populated from URL param |
| `/scans` | new | Scan history table (manual refresh) |

File layout:

```
frontend/src/routes/
    __root.tsx              (extend Header)
    index.tsx               (rewrite)
    samples.tsx             (layout route)
    samples/index.tsx
    samples/$sampleId.tsx
    scans.tsx
```

URL search params (Zod-validated via TanStack Router's `validateSearch`) on `/samples` are **deliberately minimal** to keep the schema small and avoid debounced URL churn from sliders (decision §11.19):

- In URL: `project`, `data_source`, `q`, `sort`, `order`, `limit`, `offset`, and the selected sample id (already a route param).
- In local React state (drawer): everything else — type, microscope, voltage, camera, image_format, has_tomograms, and all numeric range sliders.
- A "Copy filter URL" button on the drawer serializes the full drawer state into a longer URL when the researcher explicitly wants to share. The route's `validateSearch` accepts but doesn't *require* the extended params (every drawer field is `.optional()` in the Zod schema), so shared URLs deserialize back into the drawer.

**Round-trip data flow** (one-way): on route mount, the drawer initializes its local React state from the parsed search params; subsequent drawer edits only mutate local state and do NOT push back to the URL (that would defeat the "minimal URL" intent). The "Copy filter URL" button is the only path that serializes drawer state into a URL. Drawer state survives intra-session navigation (component stays mounted); a full reload resets the drawer to whatever the URL contained at load. Document this in the drawer component.

**Fetch-trigger debounce** (300 ms): drawer edits drive the `/samples` query, not just local state. Without throttling, dragging a `RangeSlider` (e.g. voxel-spacing min/max) fires a request on every pixel of motion. The `FilterDrawer` therefore feeds its local state into `useDeferredValue` + a 300 ms `useDebounce` hook before composing the TanStack Query `queryKey`. The debounce applies uniformly to every drawer field (chip multi-selects, sliders, toggles) so the trigger logic is one path rather than per-field. Categorical changes feel near-instant in practice (one settle after the click); slider drags collapse to a single request after the user lets go. Note: this is **separate from** the URL-write debounce that §11.19 sidesteps by not pushing drawer state to the URL at all — the 300 ms here exists purely to throttle the API call.

### 9.2 Component inventory

```
frontend/src/components/
    Header.tsx                 (extend: add /samples, /scans links)
    layout/
        AppShell.tsx           (Drawer + main content with calc(100vh - header))
        Splitter.tsx           (resizable left/right; CSS-based)
    filters/
        FilterDrawer.tsx       (left rail housing the inputs; hides rows whose facet is empty)
        ChipSelect.tsx         (multi-select chips, MUI Autocomplete-based)
        RangeSlider.tsx        (debounced apply)
        FilterClearButton.tsx
    samples/
        SamplesTable.tsx       (MUI DataGrid, controlled selection, keyboard nav)
        SampleDetailPanel.tsx  (refreshable on selection change)
        SampleHeader.tsx
        SubEntityBlock.tsx     (chromatin/synapse/simulation/freezing/milling/aunp)
        AcquisitionCard.tsx
        TiltSeriesCard.tsx     (polar plot + median-tilt preview + Neuroglancer)
        TomogramCard.tsx       (preview img + Neuroglancer button)
        AnnotationList.tsx
        WarningList.tsx
    common/
        CopyButton.tsx
        Lightbox.tsx           (MUI Dialog with maximized image)
        StatCard.tsx
        ProjectSummaryCard.tsx
        EmptyState.tsx
        LoadingSkeleton.tsx
        NeuroglancerButton.tsx (shared launch + hostname-rewrite logic; client-only useMutation)
```

### 9.3 Data fetching

- The `QueryClientProvider` is wired in `__root.tsx`, **but** the existing `/samples` route (`routes/samples.tsx:14-22`) uses raw `fetch` + `Route.useLoaderData()` — TanStack Query is not actually doing any work today. Phase 0 (§10) converts this route to the **`loader: ensureQueryData` + component: `useSuspenseQuery`** pattern (decision §11.26), before any new routes inherit it.
- New `frontend/src/api/client.ts` with `apiFetch(path, init)` that picks the right base URL: SSR reads `process.env.CRYOET_API_BASE_URL` (default `http://localhost:8000`); the browser uses `/api` (already proxied to `:8000` in dev `vite.config.ts`; production deployments need an nginx/Caddy proxy in front). Replace the ad-hoc `API_BASE` in `routes/samples.tsx`.
- New `frontend/src/api/types.ts` with hand-written response types (`SampleSummary`, `SampleDetail`, `SimulationOut`, `ChromatinOut`, etc., `TiltSeriesOut`, `FiltersOptionsOut`, `StatsOverviewOut`, `ScanOut`). Mirrors the typed-Pydantic decision (§7.8).
- Generated TS types from FastAPI's OpenAPI schema are out of MVP scope (§12).
- `NeuroglancerButton` is a **client-only mutation** — `useMutation` posting to the launch endpoint, fired only from `onClick`. SSR loaders never touch any `POST /.../neuroglancer` route; otherwise an in-process Neuroglancer viewer would spin up during SSR rendering (decision §11.20). `window.open(...)` to the launched URL is guarded with `typeof window !== 'undefined'`. Devtools (`@tanstack/react-query-devtools`) is lazy-imported / dev-only to avoid SSR-render breakage.

### 9.4 Home page (`/`)

`Stack` of cards built from `/stats/overview`:

- **Project Summary** row: one `ProjectSummaryCard` per `by_project[]` (samples, acquisitions, tomograms, size).
- **Totals** row: `StatCard`s for samples, acquisitions, tilt series, tomograms, annotations.
- **Browse** row: outlined buttons linking to `/samples`, `/scans`.
- **Last scan**: small inline string showing the most recent scan's `ended_at` and status (driven by `GET /scans?limit=1`), with a link to `/scans` for full history. No rescan button — the operator triggers rescans via `pixi run scan` (decision §11.13).

### 9.5 CryoET browser (`/samples`)

Layout: `Drawer` (left, persistent ≥ md, dismissible < md) + main content. Main content is a CSS grid `1fr 2fr` (resizable via `Splitter`).

Left = `SamplesTable` (MUI `DataGrid` keyed by `sample_id`):
- Columns: `Project`, `Sample`, `Type`, `Acquisitions`, `Tilt series`, `Tomograms`, `Warnings`.
- Counts come from extended `SampleSummary` aggregates (§7.1).
- Single-row selection drives the URL. Built-in DataGrid keyboard nav (↑/↓, Enter); override only if needed.

Right = `SampleDetailPanel` driven by route params. On `/samples` (no id), shows an `EmptyState`. On `/samples/{id}`:
1. `SampleHeader` — `{project} / {sample_id}`, type chip, warning count chip.
2. `WarningList` (collapsed if 0).
3. `SubEntityBlock` for each non-null side table (chromatin / synapse / simulation / freezing / milling / aunp).
4. For each acquisition: `AcquisitionCard` (key/value table of resolution, microscope, voltage, camera, pixel_size, tilt range, frame count, date, path with copy + "open in file browser" buttons).
5. For each tilt series: `TiltSeriesCard`:
   - Header: name + `NeuroglancerButton` (calls `POST /tilt-series/.../neuroglancer`).
   - Metadata row (n_tilts, range, voltage, pixel size, image format, microscope, camera, file size).
   - Two-column row: polar plot (`<img src=".../polar.png">`) + median tilt preview (`<img loading="lazy" src=".../preview.png">`). Both click-to-`Lightbox`.
6. For each tomogram: `TomogramCard`:
   - Shape (x×y×z), voxel spacing, pipeline / software, MRC and zarr paths with copy buttons.
   - `<img loading="lazy" src="/api/tomograms/.../preview.png">` with skeleton placeholder. Click → `Lightbox`.
   - `NeuroglancerButton`.
7. `AnnotationList` per acquisition (badge for type, files list).

### 9.6 Scans page (`/scans`)

`DataGrid` of scan runs from `GET /scans`. Columns: started_at, ended_at, root, status (chip color: running=warning, completed=success, failed=error), upserted/skipped/failed counts. Manual refresh only (decision §11.21) — a `<RefreshIcon>` button in the header re-fetches; no polling. No detail panel for MVP.

### 9.7 Theming

Extend `frontend/src/setup/theme.ts`:
- Custom palette aligned with the source dashboard's primary blue (`#1976D2`).
- Density: `small` for tables; default elsewhere.

## 10. Implementation phases

Each phase ends with a green test suite and a manually verifiable demo. The order is bottom-up: schema → parsers → API → frontend, so dependencies are satisfied before the next layer starts. **Phase 0** proves the frontend foundation works on the existing route before new routes inherit it; **Phase 4.5** is a real-data integration checkpoint between backend and frontend work.

**Phase 0 — Frontend foundation prove-out**
0a. Convert `routes/samples.tsx` to the **loader = `ensureQueryData` / component = `useSuspenseQuery`** pattern (decision §11.26). Add `frontend/src/api/client.ts` with `apiFetch(path, init)` that switches base URL on SSR vs. browser (SSR reads `process.env.CRYOET_API_BASE_URL`). Replace the ad-hoc `API_BASE`. Verify SSR + hydrate + devtools all work end-to-end on the existing route.
   - **Demo:** existing `/samples` page still renders identically, but Network tab shows the request happening through TanStack Query and the devtools panel shows the cached query.

**Phase 1 — Schema + Alembic**
1. Add `alembic` to `pixi.toml` `feature.catalog.dependencies`. Initialize `cryoet_catalog/migrations/` (env.py with `render_as_batch=True`). Generate `0001_initial.py` against the **current pre-MVP** ORM and lock it in *before* any §5.1/§5.2 changes. Capture the exact table set produced by `0001` as a frozen `BASELINE_TABLES` constant in `cryoet_catalog/db.py`. Document the legacy-DB upgrade path in `migrations/README.md`: a dev DB whose `inspect(engine).get_table_names()` equals `BASELINE_TABLES` gets `alembic stamp 0001` followed by `upgrade head`; a mismatched DB is rebuilt via `pixi run scan`.
2. Extend `cryoet_schema.schema` (Pydantic) with `TiltSeries`. Add `tomograms.size_bytes`, `acquisitions.path`.
3. Add ORM mappings in `cryoet_catalog/orm.py` (`tilt_series` table; `tomograms.size_bytes`; `acquisitions.path`). Generate `0002_dashboard_mvp.py` via `alembic revision --autogenerate`; review and clean the diff. Rewrite `init_schema` to the three-branch logic in §5.4 — including the `BASELINE_TABLES` fingerprint check that refuses to stamp a mismatched DB, and the `stamp("0001") + upgrade("head")` sequence (NOT `stamp("head")`) on the legacy branch. Drop `create_all` from the lifecycle.
4. Add `pixi run migrate` and `pixi run migrate-revision` tasks under `feature.catalog.tasks`. Update `test_orm_drift.py`. Add `tests/cryoet_catalog/test_alembic.py` (autogenerate-empty-at-head, upgrade/downgrade roundtrip, pre-MVP-DB upgrade preserves rows per table, `create_all == upgrade head` DDL drift sanity). Add `tests/cryoet_catalog/test_init_schema.py` covering the four branches per §5.4 (empty / clean-baseline / stamped-and-current / mismatched-shape — the last must refuse to stamp and leave the DB unchanged).
5. Regenerate JSON Schema files via `pixi run json-schema` (writes both `schema.json` and `acquisition.schema.json`).
   - **Demo:** existing DB upgrades cleanly via `pixi run migrate`; new `tilt_series` table appears; tests pass.

**Phase 2 — Parsers**
6. Extend `parsers/mdoc.py` to additionally return `tilt_angles: list[float]` in the parsed `fields` dict.
7. Add `cryoet_catalog/parsers/tilt_series.py` (wraps the MDOC parser; emits `TiltSeriesRecord` including the angles list and image_format detection; handles MDOC-stem collisions per decision §11.23).
8. Wire into `assembler.py`, `persistence.py` (no soft-delete cascade per decision §11.22 — `tilt_series` is left untouched on soft-delete, same as every other child table), `state.py`. Extend the `extras` write path to accept `entity_type='tilt_series'` (decision §11.24). Record `tomograms.size_bytes` and `acquisitions.path` (synthesized acquisitions included) while we're in there.
9. Tests for the parser (including the collision case) + `test_assembler_tilt_series.py` + `test_persistence_tilt_series_soft_delete.py` + `test_extras_tilt_series.py`.
   - **Demo:** scanning a fixture data root populates the new `tilt_series` table; soft-deleting a sample leaves its `tilt_series` rows in place but hidden by the API's `deleted_at IS NULL` filter; re-upsert (resurrection) brings them back into the API's view.

**Phase 3 — API: read endpoints**
10. Add `numpy`, `matplotlib-base`, `Pillow`, `neuroglancer`, `zarr`, `tifffile`, `eerfile` to `feature.api.dependencies` in `pixi.toml` (verify `eerfile` channel availability; pypi-deps if needed). Add `import matplotlib` and `import matplotlib.figure as _mpl_fig` to API startup so first-request rendering doesn't pay the import cost.
11. Add `CATALOG_DATA_ROOT` lifespan check in `api/main.py` (refuse to start if unset/non-existent; resolve once into `app.state.data_root_resolved`). Log loud warning if a multi-worker config is detected. Add the path-validation helper used by every preview/Neuroglancer route.
12. Extend `GET /samples` with all new filters + total child-row aggregate counts (correlated subqueries). Update `SampleSummary` schema. Tests.
13. New `GET /filters/options`. Tests (including empty-facet case).
14. New `GET /stats/overview`. Tests.
15. Extend `GET /samples/{id}` with `tilt_series` and typed-Pydantic `simulation`/`chromatin`/etc. Tests.
16. Confirm `GET /scans` and `GET /scans/{id}` (read-only). Tests.
   - **Demo:** curl shows filtered samples, options blob, stats blob, expanded sample detail.

**Phase 4 — API: rendering + Neuroglancer**
17. Function-extract MRC slice helper into `cryoet_catalog/imaging/_mrc.py` (provenance comment: "originally vendored from aicryoet-tools/src/aicryoet_tools/tomogram.py at commit `<sha>`"). No napari/qt imports.
18. Function-extract EER/TIFF tilt loader into `cryoet_catalog/imaging/_tilt_image.py` (sibling helpers from `aicryoet-tools/src/aicryoet_tools/eer.py`; explicitly drop the `TiltSeries`/`TiltImage` class graph from `mdoc.py`).
19. Function-extract Neuroglancer launch into `cryoet_catalog/imaging/_neuroglancer.py` (extract just `view_neuroglancer` from `aicryoet-tools/src/aicryoet_tools/visualization.py`; do NOT copy the file, which has `import napari` at module top).
20. New `GET /tomograms/.../preview.png`, `GET /tilt-series/.../preview.png`, `GET /tilt-series/.../polar.png`. Polar plot uses the matplotlib OO API (`Figure(); FigureCanvasAgg`), never `pyplot`. Tests with synthetic MRC and fixture MDOC + synthetic tilt images.
21. New `POST /tomograms/.../neuroglancer` and `POST /tilt-series/.../neuroglancer`. Bounded LRU at `app.state.active_viewers` guarded by `asyncio.Lock`, threadpool launch. Smoke tests marked `slow` + LRU eviction test + concurrent-launch race test.
22. `test_api_path_validation.py`: every preview/Neuroglancer route 404s for paths outside `CATALOG_DATA_ROOT` (including symlink-traversal cases).
   - **Demo:** browser opens each preview URL and sees an image; Neuroglancer opens for both tomograms and tilt series; preview/Neuroglancer routes refuse paths outside the data root.

**Phase 4.5 — Real-data integration checkpoint** *(run 2026-05-11; gate revised — see findings below)*
23. Run `pixi run scan` against a real researcher data root (not synthetic fixtures). Record any parse errors or warnings.
24. Curl every new endpoint with at least one real row id from each: `/samples` (with each filter exercised at least once), `/filters/options`, `/stats/overview`, `/samples/{id}`, `/tomograms/.../preview.png`, `/tilt-series/.../preview.png`, `/tilt-series/.../polar.png`, `/scans`. Eyeball every response.
25. Look for surprises: NULL `microscope` everywhere (= TOMLs need updating), empty filter facets, broken paths, slow endpoints, missing fields the frontend will need. Open issues for anything that needs fixing before frontend phases. Update the plan if scope changes.

**Run results (2026-05-11, root `/groups/cryoet/cryoet/data/scratch/data/`):**
- Scan: 5 samples upserted, 0 skipped, 70 warnings, 0 errors.
- Warning categories: `undeclared_tomogram_folder × 38`, `undeclared_annotation_folder × 12`, `missing_acquisition_toml × 12`, `unfilled_placeholder × 8`.
- Endpoints exercised: `/samples`, `/filters/options`, `/stats/overview`, `/samples/{id}`, `/scans`, `/tilt-series/.../polar.png` → all 200. `/tilt-series/.../preview.png` → 422 on every row. Tomogram + Neuroglancer endpoints not exercisable (see finding #3).

**Findings:**
1. **gouauxlab per-tilt MDOC layout collapses to N tilt-series rows instead of 1.** Each EER frame has a sibling `.mdoc`; `parsers/tilt_series.py::parse_tilt_series_dir` emits one row per MDOC, producing ~33 spurious tilt-series rows per acquisition. Affects all 4 `gouauxlab_*` samples. Reference impl: `aicryoet-tools/src/aicryoet_tools/mdoc.py::get_tilt_angles` already handles the series-level-vs-per-tilt distinction. Parser+assembler+persistence fix, ~½ day.
2. **Rosenlab tilt-series are EER-only with no zarr and no `.st` stack.** Preview route skips EER at request time (too slow) and the frames-dir TIFF/MRC fallback finds nothing. Polar works because angles are cached on the row. Two unblocks: (a) pre-render zarr next to one MDOC via `aicryoet-tools` converter for the demo, or (b) accept slow-EER preview as a follow-on with disk-cached output. Also cheap-and-incremental: teach the preview route to read `.st` stacks (slice N/2 of the MRC-format stack) when `st_path` is set.
3. **Zero tomograms in DB.** 38 `undeclared_tomogram_folder` warnings — directories exist on disk but no acquisition TOML declares them. Tomogram preview + Neuroglancer surfaces stay untested until upstream TOML coverage improves. Same TOML-coverage finding hits `undeclared_annotation_folder` and `missing_acquisition_toml`.

**Gate revised — finding #1 is a hard prereq for Phase 5; findings #2 and #3 are not.** Finding #1 (gouauxlab parser bug) distorts the *data model* (66+ spurious tilt-series rows across 4 samples) so any frontend work would be coded against bad cardinality and bad stats. Findings #2 (EER-only, no zarr/`.st`) and #3 (TOML coverage / zero tomograms) only block the *success path* of preview/Neuroglancer endpoints — they're surfaces with empty/error states, not bad data. So Phase 4.6 is added as a hard prereq to Phase 5; findings #2 and #3 stay tracked outside this plan.

**Phase 4.6 — Gouauxlab per-tilt MDOC parser fix** *(prereq for Phase 5)*

Detects per-tilt MDOC layouts (multiple `.mdoc` sidecars in one frames dir, one per EER frame, no `[ZValue]` sections) and collapses N spurious tilt-series rows into 1 correct row whose `tilt_angles` is the list of angles extracted from per-tilt MDOC filenames. Reference: `aicryoet-tools/src/aicryoet_tools/mdoc.py::get_tilt_angles` already handles the series-level-vs-per-tilt distinction.

23a. Add layout classifier to `cryoet_catalog/parsers/tilt_series.py`: series-level (any MDOC contains `[ZValue`, sniff first 2KB) vs per-tilt (multiple MDOCs, none with `[ZValue`, filenames match `_NNN_<angle>` regex) vs unknown. Helper `is_series_level_mdoc(path)` in `parsers/mdoc.py`.
23b. Per-tilt collapse path: emit one `TiltSeriesRecord` per unique filename-prefix group, with `tilt_angles` = `[extract_tilt_angle_from_filename(m.name) for m in mdocs]`, `n_tilts` = `len(tilt_angles)`, derived `tilt_range_min/max`. `tilt_series_id` = longest-common-prefix of MDOC filenames with trailing `_NNN_<angle>...` stripped (e.g. `20241211_HippWaffle_49`); falls back to `acquisition_id` on tie. `mdoc_path` = first MDOC in sorted order.
23c. Mixed dirs: one record per unique-prefix group. Stem-collision logic in `_disambiguate_ids` preserved at group granularity.
23d. New warning category `tilt_series_layout_unknown` for directories where neither classifier matches (loud-but-non-blocking, same convention as `tilt_series_id_collision`).
23e. No assembler / persistence changes expected. `_delete_stale_children` already prunes rows whose composite PK isn't in the new upsert set — the 32 spurious gouauxlab rows per acquisition prune automatically on re-scan.
23f. Tests: per-tilt collapse, mixed-group emission, unparseable-filename warning + angle drop, series-level regression, assembler integration, stale-row pruning regression.
23g. Deployment: wipe + `pixi run scan --init` against real data root (mtime gating won't fire on parser-logic changes; `--force` would also work). Verify `gouauxlab_*` samples now report 1–2 tilt-series per acquisition and total tilt-series count drops from 66+ to ~10-15.
   - **Demo:** `/tilt-series/<gouauxlab_sample>/<acq>/<ts>/polar.png` produces a meaningful multi-angle plot, not a single radial line.

Effort ~½ day. Risk low — additive change (per-tilt path is new code; series-level path unchanged and confirmed working against rosenlab data).

**Phase 5 — Frontend infrastructure**
26. Add Zod-validated search params on `/samples` (minimal schema per §9.1, every drawer field `.optional()`).
27. Wire MUI `Drawer` + responsive `AppShell`. Extend `Header` with new links.
28. Build shared components: `FilterDrawer` (with empty-facet hide-on-mount logic per decision §11.25, and the 300 ms `useDebounce` on the drawer-state → query-key path per §9.1 / §11.19 — single debounce path applied uniformly to every drawer field), `ChipSelect`, `RangeSlider`, `Lightbox`, `CopyButton`, `StatCard`, `NeuroglancerButton` (client-only mutation per §9.3), "Copy filter URL" button.
29. Hand-write `frontend/src/api/types.ts` mirroring the typed-Pydantic schemas from §7.8.

**Phase 6 — Frontend home + scans**
30. Replace `index.tsx` with `ProjectSummaryCard` + `StatCard`s + browse links + "Last scan" inline status.
31. New `/scans` route (read-only history table; Refresh button, no polling).

**Phase 7 — Frontend CryoET browser**
32. `SamplesTable` (DataGrid) replacing the plain HTML table. Selection drives nested route.
33. `SampleDetailPanel` + `SubEntityBlock` + `AcquisitionCard` + `AnnotationList` + `WarningList`.
34. `TomogramCard` with lazy preview + Lightbox + `NeuroglancerButton`.
35. `TiltSeriesCard` with polar plot + median-tilt preview + `NeuroglancerButton`.

**Phase 8 — Polish**
36. Loading skeletons + empty states everywhere.
37. Error boundary on each route with a Snackbar + retry.
38. **Manual smoke checklist** (decision §11.27): document a click-path checklist in `README.md` covering home → /samples filter → row select → detail panel sub-entities + tilt-series card + tomogram card → Neuroglancer launch → lightbox → /scans Refresh. No automated browser tests for MVP.
39. Update top-level `README.md` with the new routes/endpoints, the new env vars (§8), the `--workers 1 --no-reload` deployment note, the `pixi run migrate` workflow, and the production reverse-proxy expectation.

## 11. Decisions resolved in planning

The original plan flagged a dozen open questions; all were settled before writing code. Recording them here so the rationale lives with the plan.

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 11.1 | `acquisitions.path` column | Add it | Unlocks copy + "open in file browser" buttons; scanner records the directory containing the acquisition's MDOC / first MRC. Synthesized acquisitions get the path the scanner walked |
| 11.2 | `tomograms.size_bytes` column | Add it | One extra `os.stat` per tomogram at scan time; enables home-page size stats and per-card size badges |
| 11.5 | New runtime deps | `numpy`, `matplotlib-base`, `Pillow`, `neuroglancer`, `zarr`, `tifffile`, `eerfile` in `feature.api.dependencies` | Non-negotiable for rendering features. `matplotlib-base` (not `matplotlib`) avoids pulling Qt — consistent with dropping OVITO/PySide6/PyQt6/napari/nicegui. `eerfile` channel verified before phase 3; pypi-deps fallback if needed |
| 11.6 | Source of MRC/EER/Neuroglancer helpers | **Function-extract** into `cryoet_catalog/imaging/` (not file-copy) | `aicryoet-tools/visualization.py` does `import napari` at module top; `eer.py` siblings reference a 500-line `TiltSeries`/`TiltImage` class graph from `mdoc.py`. We pull only the specific functions we need — `view_neuroglancer` into `_neuroglancer.py`, the MRC slice helper into `_mrc.py`, `load_tilt_image` into `_tilt_image.py` — each with a provenance comment at file head ("originally vendored from aicryoet-tools/<path> at commit `<sha>`"). Tradeoff: vendored functions will drift; treat them as our code from now on |
| 11.7 | Polar-plot tilt-angle storage | Cache `tilt_angles` JSON column on `tilt_series`; cache key on render = `(tilt_series PK, mtime_of_mdoc, POLAR_RENDER_VERSION)` | One MDOC parse at scan time; fast renders forever after. ~1 KB per row. mtime guards against re-acquisitions; the manual `POLAR_RENDER_VERSION` bump invalidates the cache when the renderer changes |
| 11.8 | URL design for composite-key resources | Composite-key URLs throughout (e.g. `/tilt-series/{sample_id}/{acquisition_id}/{tilt_series_id}/preview.png`); `tilt_series_id` scoped per-acquisition (PK = `(sample_id, acquisition_id, tilt_series_id)`) | Self-describing; no server-side hash table to maintain. Verbose but explicit. Per-acquisition scoping means `tilt_series_id` is just the MDOC stem (with collision-disambiguating suffix when needed — §11.23) |
| 11.9 | Neuroglancer in production | Document `--workers 1 --no-reload` for MVP in README; bounded LRU at `app.state.active_viewers` (default 8) guarded by `asyncio.Lock`; lifespan logs loud warning on multi-worker; production hardening is a follow-on | Neuroglancer binds an HTTP server once per process — multi-worker or autoreload breaks viewer launches. Bounded LRU + lock prevents the unbounded memory leak the source dashboard has, and avoids race-condition double-eviction |
| 11.10 | Auth / network exposure | None; trusted-network only | Same posture as the source dashboard. API and Neuroglancer bind to `0.0.0.0` for VPN/internal use |
| 11.12 | DB migrations | Adopt **Alembic**; rewrite `init_schema` to a three-branch detect (alembic_version → upgrade; legacy ORM tables → stamp+upgrade; empty → upgrade); drop `create_all` from the lifecycle | `Base.metadata.create_all` cannot add columns or rename. The MVP delta touches 3 tables. Alembic gives us reviewable revision history from day one. SQLite-specific caveats: `render_as_batch=True` (rebuilds tables, drops manual indexes), autogenerate misses CHECK changes; document in `migrations/README.md`. Older dev DBs that don't match the `0001` baseline are rebuilt via re-scan |
| 11.13 | Scan trigger surface | CLI-only for MVP | `POST /scans/rescan` is dropped from MVP. `pixi run scan` is the only entry point. Drops the BackgroundTasks-vs-asyncio-vs-process-pool decision, the 409-race concern, and the API-as-a-second-writer concern. The frontend `/scans` page and home-page "last scan" inline are read-only |
| 11.14 | microscope/camera source | `acquisition.toml` only | MDOC parser stays focused on tilt-series fields; researchers populate microscope/camera explicitly in `acquisition.toml`. Tradeoff: filter facets will be empty until TOMLs are updated — accepted because it forces an authoring habit and keeps the parser layered. Empty facets are hidden in the UI (§11.25) |
| 11.15 | `SampleSummary` aggregate counts | Total child rows, filter-independent | Stable display: a sample with 3 tomograms always reads "3" regardless of active filters. Cheaper query (correlated subquery vs. recomputing the full filter join) and matches user intuition |
| 11.16 | `CATALOG_DATA_ROOT` enforcement | Required at startup; resolved once into `app.state.data_root_resolved`; every preview/Neuroglancer route 404s for paths outside it | Defense in depth against API/scanner host divergence (HHMI norm) and against symlink-traversal escapes from absolute paths recorded in the DB. **Caveats documented in `migrations/README.md` and route docstrings**: TOCTOU between `resolve(strict=True)` and the actual file open is acceptable on trusted-network; Zarr internal symlinks (chunks pointing outside the resolved Zarr dir) are not blocked — Zarr stores must not contain external symlinks |
| 11.18 | Sub-entity schema shape | Typed Pydantic per side-table (`SimulationOut`, `ChromatinOut`, etc.) | `dict[str, Any] \| None` is rejected. Frontend types match field-by-field; OpenAPI is precise. More boilerplate is the cost. `SimulationOut` matches the existing `Simulation` Pydantic model — no MD-specific fields are added in this MVP (§14) |
| 11.19 | URL filter scope | Minimal URL params (project/data_source/q/sort/order/limit/offset/selected id); drawer state in local React state initialized from search params on mount, **not pushed back**; "Copy filter URL" button as escape hatch. **Fetch-trigger debounce: 300 ms** on the drawer-state → query-key path so slider drags don't fire 60 requests/sec (§9.1) | Keeps the Zod schema small, avoids debounced URL churn from sliders, still allows shareability on demand. The 300 ms fetch debounce is a separate concern from URL-write debounce: even though drawer state never reaches the URL, it still drives the API call and needs throttling. Tradeoff: drawer state doesn't survive reload by default — documented in the drawer component |
| 11.20 | `NeuroglancerButton` lifecycle | Client-only `useMutation`, fired only on click; `window.open` guarded with `typeof window !== 'undefined'`; devtools lazy-imported | SSR loaders never call any `POST /.../neuroglancer` route; otherwise the in-process viewer would spin up during SSR rendering. `mutation.data` lives in component state per-instance — no extra persistence needed for MVP since the URL is consumed immediately |
| 11.21 | `/scans` page liveness | Manual refresh only (Refresh button) | Cheapest. Matches operator workflow (CLI scan, eyeball /scans afterward). Polling and SSE deferred — no concrete need |
| 11.22 | Soft-delete behavior for `tilt_series` | **No cascade** — leave rows in place, same as every other child table | Matches the existing convention documented in `persistence.py:317-320` ("Child entities ... are intentionally NOT touched: soft delete preserves history so a sample can be resurrected by a later upsert"). Departing from that convention only for `tilt_series` would create a confusing inconsistency. Orphan-leakage via API filters is already prevented by the outer `samples.deleted_at IS NULL` clause; no cascade is needed for correctness. Resurrection's existing re-upsert flow updates `tilt_series` rows just like it updates `tomograms`/`annotations` today. **Defense-in-depth against long-lived orphans is a separate, deferred concern** — if it becomes a real problem we can add a maintenance task that vacuums child rows whose parent has been soft-deleted for >N days, applied uniformly to all child tables. That decision should not be entangled with the cascade hook |
| 11.23 | MDOC-stem collisions | Auto-disambiguate (parent-dir suffix, then numeric) + emit `tilt_series_id_collision` warning | Both tilt series are catalogued; researchers see the warning in `/scans`. Loud-but-non-blocking |
| 11.24 | `extras` for new entity types | Allow `entity_type='tilt_series'` | TOML `[[tilt_series]]` extras round-trip like acquisitions/tomograms today; researchers can attach custom metadata without schema churn |
| 11.25 | Empty filter facets in the UI | Hide the row entirely; URL schema still validates the param | Cleanest first-day UX; old shared URLs round-trip. As facets fill in (TOMLs get populated) the rows reappear |
| 11.26 | Phase 0 TanStack Query pattern | `loader: ensureQueryData` + component: `useSuspenseQuery` | SSR-safe, type-safe, matches current TanStack Start docs. Pinning the pattern means new routes have a clear template |
| 11.27 | Frontend smoke-test scope | Manual click-path checklist documented in `README.md` | Cheapest. Catches regressions only when read; an explicit tradeoff. Playwright is a follow-on once the surface area is stable |

### 11.x Implementation risks to watch

- **Vendored-helper drift.** `cryoet_catalog/imaging/` starts as function-extracts (not file-copies) from `aicryoet-tools`. Bug fixes won't auto-flow either way. Document the "originally vendored from aicryoet-tools/<path> at commit `<sha>`" provenance in each file header.
- **Polar-plot row size.** `tilt_angles` JSON of ~120 floats ≈ 1 KB per row. Acceptable today; revisit if tilt-series counts grow into the tens of thousands.
- **Multi-worker Neuroglancer.** Single-worker uvicorn is fine for MVP but not a hardened production posture. Track as a follow-on.
- **Alembic autogenerate gaps on SQLite.** `render_as_batch=True` is mandatory for ALTER TABLE and **rebuilds the table**, dropping manual indexes/PRAGMAs. Autogenerate misses CHECK constraint changes and some default-value changes. Every revision diff must be reviewed before commit; document in `cryoet_catalog/migrations/README.md`. Pre-MVP-DB upgrade tests assert per-table row counts to catch silent rebuild data loss.
- **`init_schema` rewrite.** The three-branch logic must be tested against three real cases: empty DB, legacy DB matching baseline, legacy DB with `alembic_version` already present. Skipping any one of these can leave a developer's DB in a stamped-but-not-upgraded state.
- **Phase 4.5 may surface scope changes.** ~~If real-data integration uncovers parser issues or missing fields, frontend phases pause until backend fixes land.~~ **Updated 2026-05-11 after running the checkpoint:** the checkpoint surfaced three findings — (#1) gouauxlab per-tilt MDOC parser bug; (#2) rosenlab EER-only with no zarr/`.st`; (#3) zero tomograms due to TOML coverage gaps. Finding #1 distorts the data model so it was promoted to **Phase 4.6 as a hard prereq for Phase 5**. Findings #2 and #3 only block the success path of preview/Neuroglancer endpoints (empty/error states are fine first-day UX) and stay tracked outside this plan. See Phase 4.5 + 4.6 sections in §10.
- **Manual smoke checklist may rot.** Without Playwright, the README checklist is the only regression net. Plan to revisit once the surface area stabilizes.
- **Zarr internal symlinks.** Path validation walks the top-level Zarr dir but doesn't validate every chunk inside. Document the "no external symlinks inside Zarr stores" expectation in the data-organization guide; not gated on enforcement code for MVP.

## 12. Out of scope (deferred / follow-on)

- All MD / simulation work — see **§14**.
- Authentication, RBAC, audit logging.
- Production deployment hardening (multi-worker safe Neuroglancer, distributed preview cache, CDN for previews).
- OpenAPI-generated TypeScript client.
- Save-tilt-series-to-MRC/TIFF, contrast adjustment, batch tilt-series load, CTF estimation (see `aicryoet-tools/dev_notes/ROADMAP.md`).
- Tomogram ↔ tilt-series derivation FK. Both are FK'd to acquisition only in MVP; the "reconstructed from" relationship is deferred until researchers have a clear convention for expressing it.
- Playwright / browser smoke tests. MVP relies on a manual click-path checklist (§11.27).
- `/scans` polling or SSE. Manual refresh only (§11.21).

## 13. Acceptance criteria

- Scanning a fixture data root populates `samples`, `acquisitions`, `tilt_series`, `tomograms`, and `annotations` rows with the expected metadata. Soft-deleting a sample leaves its `tilt_series` rows in place (same convention as the other child tables); the rows are hidden from the API by the outer `deleted_at IS NULL` filter, and resurrection via re-scan brings them back into view.
- Home page renders project summary + totals from a freshly scanned dev DB.
- `/samples` filters, sort, and selection round-trip through the URL (URL-level params); drawer state initializes from search params on mount and is shareable via "Copy filter URL".
- Selecting a cryoET sample shows all sub-entities, acquisitions, tilt-series cards (with working polar plot, working median-tilt preview, working Neuroglancer button), tomograms (with working preview + Neuroglancer button), annotations, and warnings.
- "View in Neuroglancer" opens a working viewer in a new tab for at least one fixture tomogram and one fixture tilt series. Concurrent launches at capacity don't crash the API.
- Running `pixi run scan` mutates the DB; the new `scan_run_id` appears on the `/scans` page (manual refresh) and in the home-page "Last scan" inline within the next page load.
- `pixi run migrate` upgrades a pre-MVP DB matching the `0001` baseline to head without data loss; per-table row counts pre/post are equal.
- Phase 4.5 integration checkpoint completed against real researcher data; findings logged and triaged. Phase 4.6 (gouauxlab per-tilt MDOC parser fix) lands before Phase 5. The other two upstream findings (rosenlab EER-only tilt-series, TOML coverage gaps for tomograms/annotations) are tracked outside this plan and do not block Phase 5–8. Golden-path demo (preview image + Neuroglancer launch on real data) additionally requires one of: (a) one rosenlab MDOC's EERs pre-rendered to zarr; (b) TOML cleanup unlocking ≥1 tomogram row; (c) `.st` reader added to the preview route.
- API refuses to start without `CATALOG_DATA_ROOT`; preview/Neuroglancer routes 404 for paths outside it.
- All new backend endpoints have unit tests passing under `pixi run test`.
- The frontend boots cleanly under `pixi run frontend` and the API under `pixi run api` (with `--workers 1 --no-reload`) against a freshly scanned `cryoet_catalog.db`.
- The README documents the new routes, env vars (including `CRYOET_API_BASE_URL` and the production reverse-proxy expectation), `pixi run migrate` workflow, and the manual smoke-test checklist.

## 14. Future steps: simulation / MD support

This work is **deferred** because the catalog has no simulation data yet. When MD samples start arriving, the work below extends the MVP. Designs are recorded here so the prior planning isn't lost.

### 14.1 Schema

- New tables: `dump_files` (one LAMMPS dump file per row, FK on `sample_id`; PK `(sample_id, dump_id)`; columns `path`, `name`, `size_bytes`, `n_frames`, `n_atoms`, `box_x`, `box_y`, `box_z`, `preview_path`, `mtime`, denormalized `simulation_type`) and `analysis_files` (LAMMPS data / fiber-config files; PK `(sample_id, analysis_id)`; columns `path`, `name`, `n_atoms`, `n_bonds`, `size_bytes`, `mtime`).
- **REMD support**: include `replica_index: int | None` and `temperature_k: float | None` on `dump_files` so the REMD category in the UI can sort and label cards correctly. (Open question from review — confirm against real REMD data when it arrives.)
- Soft-delete behavior for both new tables follows the existing convention (rows left untouched on soft-delete; resurrection re-upserts), mirroring `tilt_series` and every other child table (§11.22).
- `extras` accepts `entity_type IN ('dump_files', 'analysis_files')`.
- Extend the existing `simulation` side-table with MD-specific fields ported from `aicryoet-tools/src/aicryoet_tools/catalog/schema.py:121`: `simulation_type` (alongside `dataset_type` for one release; a Pydantic `model_validator` mirrors them and warns on legacy use; remove `dataset_type` once `SELECT COUNT(*) WHERE dataset_type IS NOT NULL AND simulation_type IS NULL = 0`), `linker_*`, `n_nucleosomes`, `n_base_pairs`, `salt_concentration`, `temperature_k(_max)`, `is_remd`, `n_atoms`, `box_*`, `preview_path`, `coord_style`, `pbc_*`, `wrap_periodic`, `status`.

### 14.2 Parsers + scanner

- New parsers: `cryoet_catalog/parsers/lammps_dump.py` (header-only byte-streamed; port subset of `aicryoet-tools/src/aicryoet_tools/load_lammps_dump.py`), `lammps_data.py`, `md_simulation.py` (heuristics from `aicryoet-tools/src/aicryoet_tools/catalog/labs/collepardolab.py`).
- `assembler.py` reads `data_source` from TOML (assembler.py:154 already calls `load_sample_toml`) and routes to the LAMMPS parsers when `data_source == "simulation"`. Discovery stays content-blind.
- Extend `discovery.parse_targets_for_sample` to include `*.dump`, `data.txt`, and `new_data_*.txt` for mtime gating. **Recursive walk under the sample dir with depth limit 3**; emit a warning if anything is found below the limit (REMD trees may be deeper). Branch runs unconditionally on every sample dir — parse_targets_for_sample currently iterates acquisitions, but simulation samples have none, so the dump-file branch is a separate unconditional walk.

### 14.3 API

- New filters on `/samples`: `simulation_type`, `linker_length_min/max`, `n_nucleosomes_min/max`, `n_base_pairs_min/max`, `salt_min/max`, `temperature_min/max`, `is_remd`.
- `/filters/options` gains `simulation_types`, `statuses`, `linker_length`, `n_nucleosomes`, `n_base_pairs`, `salt`, `temperature` ranges.
- `/stats/overview.totals` gains `dump_files`.
- New endpoints: `GET /md-samples/{sample_id}/preview.png`, `POST /md-samples/{sample_id}/render-preview` (idempotent; `?force=true` to re-render), `GET /md-samples/extras/info` (static markdown for the info dialog).
- `GET /samples/{sample_id}` gains `dump_files: list[DumpFileOut]` and `analysis_files: list[AnalysisFileOut]`. `SimulationOut` extends with the new MD fields.
- New `cryoet_catalog/imaging/md_preview.py`: matplotlib 3D scatter on the **OO API** (`Figure(); FigureCanvasAgg`), hand-written palette tuned for matplotlib's white background, `run_in_threadpool`-wrapped.
- **Preview cache location**: per-API cache dir `CATALOG_PREVIEW_CACHE_DIR` (default `~/.cache/cryoet-catalog/previews/`). DB column `simulation.preview_path` points into the cache dir, recomputed lazily. Keeps the data root read-only.

### 14.4 Frontend

- New routes `/simulations` and `/simulations/$sampleId` (filter rail + simulations table + detail panel).
- New components: `SimulationsTable`, `SimulationDetailPanel`, `DumpCard`, `DumpGroup` (ports `_DUMP_CATEGORIES`), `ParticleColorLegend` (palette ported from `cryoet_catalog/imaging/md_preview.py`), `MdInfoDialog` (markdown via `react-markdown`).
- MD sub-block on `/samples/{id}` detail panel — same data, two entry points.

### 14.5 Risks / open questions

- **TOML simulation-block schema.** Researchers haven't authored simulation TOMLs yet. Phase 1 of the follow-on should ship with a documented `[simulation]` block in `templates/` and at least one fixture sample.
- **MD preview frame selection.** "Last frame" is a sensible default but for REMD trajectories the last frame may be at the highest replica temperature. Punt to a `?frame=N` query param.
- **REMD column shape on `dump_files`.** Confirm `replica_index` / `temperature_k` against real data layout before locking the schema.
