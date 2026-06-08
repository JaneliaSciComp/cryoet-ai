# Plan: Pre-generated tomogram thumbnails (filesystem cache) for sample / acquisition / tomogram views

**Date:** 2026-06-05
**Status:** Ready for implementation (all open questions resolved)
**Author:** planning session (Claude)

## Summary

Today the portal renders preview images **on the fly** at request time:

- The tomogram table on `/acquisitions/$acquisitionId` points each row at
  `GET /tomograms/{s}/{a}/{t}/preview.png`, which decodes the MRC + renders the
  center-XY slice with matplotlib on every request (LRU-cached in API process
  memory only — `tomograms.py:57-108`).
- The acquisition rows on `/samples/$sampleId` point at the **tilt-series**
  center preview `GET /tilt-series/{s}/{a}/{ts}/preview.png`
  (`SampleAcquisitionsTable.tsx:20-29`).
- The browse-page sample column and the two detail-page "hero" slots are static
  `<ThumbnailPlaceholder>` grey boxes (`SamplesPortalTable.tsx:27`,
  `samples.$sampleId.tsx:140`, `acquisitions.$acquisitionId.tsx:118`).

We are changing the **tomogram-derived thumbnails** to be **pre-generated during
the filesystem scan** and written to a **thumbnail cache directory on disk**, 
so the API just streams a cached PNG instead of decoding MRCs per request. The
cache can be deleted and is **auto-rebuilt by re-running a plain scan** (the
skip path self-heals missing thumbnails — see Step 5b); `--force` also rebuilds.

### Behavior to implement (from the request)

1. **Per tomogram** (`/acquisitions/$acquisitionId`, tomogram table row): a
   center-XY-slice thumbnail, generated like the `aicryoet-tools` prototype
   (already vendored as `imaging/_mrc.render_center_xy_slice_png`).
2. **Per acquisition** (acquisition row under `/samples/$sampleId`): use the
   **post-processed tomogram's** thumbnail; if absent, the **raw tomogram's**;
   if neither, the placeholder.
3. **Per sample** (sample detail "hero" on `/samples/$sampleId` **and** the
   sample column on the main browse page): use the acquisition thumbnail; if a
   sample has more than one acquisition, use the **first** acquisition (ordered
   by `acquisition_id`, matching the API's existing ordering).
4. **Future (not in this plan):** a schema-level "representative tomogram" flag
   the researcher sets, which would drive both the acquisition and sample
   thumbnail. The design below isolates the selection rule so swapping in that
   flag later is a one-function change.

## Key constraints discovered (ground truth in the codebase)

- **The data root is mounted READ-ONLY.** `docker-compose.yml` mounts
  `${CATALOG_DATA_ROOT}:${CATALOG_DATA_ROOT}:ro` in *both* the `api` and
  `scanner` services. => The thumbnail cache **cannot** live under
  `CATALOG_DATA_ROOT`. It needs its own writable location, shared between the
  (writing) scanner and the (reading) API — exactly like the existing
  `catalog-db` named volume.
- **The scanner pixi env can't render images yet.** The scanner runs in the
  `catalog` feature (`pyproject.toml:61-64` → `sqlalchemy`, `mrcfile`,
  `alembic`). `numpy` / `matplotlib-base` / `pillow` are only in the **`api`**
  feature (`pyproject.toml:70-79`). `imaging/_mrc.py` imports `numpy` and
  `matplotlib` at module top, so importing it in the scanner env fails today.
  => We must add `numpy` + `matplotlib-base` to the `catalog` feature (mrcfile
  is already there). matplotlib's Agg `print_png` needs no pillow.
- **`Dockerfile.scanner` already builds `-e catalog`**, so once the deps are in
  that feature the scanner image picks them up with a `pixi.lock` refresh.
- **Schema bootstrap is `create_all`, not Alembic.** `db.init_schema` calls
  `Base.metadata.create_all` (`migrations/versions/` is empty). New ORM columns
  appear automatically on fresh / test DBs; only pre-existing on-disk DBs need a
  manual `ALTER TABLE` (Step 8).
- **DB-only column precedent = `disk_size_bytes` / `deleted_at`.** A scanner-
  computed, per-sample column that is *not* in the `cryoet_schema` Pydantic
  model: added to `SampleORM`, carved out of `test_orm_drift.py`
  (`test_orm_drift.py:46` already lists `{"deleted_at", "disk_size_bytes"}`),
  and injected into `sample_payload` before `session.merge` in
  `persistence.upsert_sample_record` (`persistence.py:163-165`). Our
  `thumbnail_path` follows this exact pattern.
- **Scanner gating.** `_scan_one_sample` (`scanner.py:147-213`) skips a sample
  whose parse-target files are unchanged. `disk_size` is computed only on the
  non-skip path (`scanner.py:191`). Thumbnails will be (re)generated on the same
  non-skip path => same staleness model: refresh on parse-target change or
  `--force`. (See Open Questions re: cache-blown-away + plain rescan.)
- **`imaging/_mrc.render_center_xy_slice_png(mrc_path, *, width=1200)`** already
  does exactly the center-slice render we want and returns **PNG bytes** (not a
  data URI). We reuse it with a smaller `width`.
- **`SampleSummary` carries no child entities** (`schemas.py:17-30`; the list
  query returns only counts). => The browse-page sample thumbnail is the *only*
  place that needs a server-resolved pointer; everywhere else the frontend
  already has the tomogram ids in `SampleDetail` / `AcquisitionOut` and can build
  the URL itself.
- **`PreviewThumbnail` already falls back to the placeholder on `onError`**
  (`Thumbnail.tsx:47-76`). => A thumbnail URL that 404s (no cached file)
  degrades to the grey box automatically; the API need not pre-confirm existence
  for the per-tomogram / per-acquisition / sample-detail cases.

## Design decisions (made; challengeable in review)

- **Cache is a generic, relative-path-addressed PNG store.** Files live at
  `{thumbnail_root}/{sample_id}/{acquisition_id}/{tomogram_id}.png`. One PNG per
  tomogram that has a readable `mrc_path`. Deterministic path ⇒ the frontend can
  construct the URL from ids it already holds; no per-tomogram DB column needed.
- **One serving endpoint:** `GET /thumbnails/{relpath:path}` streams
  `{thumbnail_root}/{relpath}` (path-validated to stay under the root), 404 if
  missing. Mirrors the `Cache-Control`/`Response` shape of the existing preview
  routes.
- **Only ONE new DB column + ONE new response field:**
  - `SampleORM.thumbnail_path: str | None` (DB-only) — the sample's
    representative relpath, computed by the scanner via the selection rule, used
    by the **list** endpoint.
  - `SampleSummary.thumbnail_path: str | None` in the API response.
  - Per-tomogram, per-acquisition, and sample-detail thumbnails are resolved
    **client-side** from data the frontend already has, + 404→placeholder.
- **Selection rule (isolated in one helper, `thumbnails.representative_relpath`):**
  per acquisition: first `post_processed_tomogram` (by `tomogram_id`) with a
  generated thumbnail, else the `raw_tomogram` if it has one. Per sample
  (**Q4 resolved — fall through**): apply the rule to the first acquisition (by
  `acquisition_id`) that yields a thumbnail, falling through to later
  acquisitions if the first has none. So a sample shows a thumbnail whenever
  *any* of its acquisitions has a renderable tomogram. Swapping in the future
  "representative tomogram" schema flag replaces just this one function.
- **Thumbnail width = 512px** (Q5), percentile **(1, 99)** (the `_mrc` default),
  **no height cap** — CSS `object-fit` fits the slice into the 96×64 rows and the
  220px hero. Lightbox/full-res, if added later, can keep using the 1200px
  on-the-fly `preview.png`.
- **Generation only from `mrc_path`** (Q6 — the data is mostly MRC). Tomograms
  with only a `zarr_path` get no thumbnail in v1 (→ placeholder). A zarr
  center-slice renderer is explicitly deferred.
- **Cache rebuild = auto-heal on a plain scan (Q2).** The scanner's skip path
  does one `stat` on the sample's stored representative thumbnail; if missing
  (and `thumbnail_path` is non-null), it regenerates that sample's thumbnails
  from its existing DB tomogram rows and updates `thumbnail_path`. Steady-state
  cost is ~one stat per skipped sample; the k8s CronJob self-heals a lost
  volume. `--force` still rebuilds everything via the normal upsert path.
- **Cache location is pure config (Q1):** dev →
  `/groups/cryoet/cryoet/data/scratch/thumbnails` (sibling to the test data,
  **outside** `CATALOG_DATA_ROOT` so the scan/`dir_size_bytes` walk never sees
  it); prod (k8s) → a mounted volume. Both via the single `CATALOG_THUMBNAIL_DIR`
  env var.
- **Keep the existing on-the-fly `preview.png` endpoints** (`tomograms.py`,
  `tilt_series.py`) intact for now — harmless, and a natural full-res / lightbox
  source. The table rows simply stop pointing at them.
- **`config = env var `CATALOG_THUMBNAIL_DIR`.** Read by both scanner (CLI/env)
  and API (lifespan → `app.state.thumbnail_root`).

## Non-goals

- No "representative tomogram" schema field (future work; rule is isolated).
- No zarr-volume or tilt-series-derived thumbnails (mrc center slice only).
- No change to the `/acquisitions/$acquisitionId` **hero** slot (the "Tilt
  series" placeholder) — out of scope; the request targets the acquisition
  *row* under `/samples/$sampleId`.
- No real-time per-request rendering for the new thumbnails (the whole point is
  to pre-bake them).
- No Alembic migration authored now (deferred repo-wide; Step 8 gives the manual
  `ALTER TABLE` for existing DBs).

## Implementation steps

### Step 1 — pixi deps: let the scanner render

`pyproject.toml`, `[tool.pixi.feature.catalog.dependencies]` (lines 61-64): add

```toml
numpy = ">=1.26"
matplotlib-base = ">=3.8"
```

Then refresh the lock (`pixi install`/`pixi lock`) so `Dockerfile.scanner`'s
`pixi install --locked -e catalog` resolves them. `tests/test_deps_in_sync.py`
only enforces the schema+test deps, so this won't trip it — **verify** that
assumption when running tests.

### Step 2 — ORM: add `SampleORM.thumbnail_path`

`cryoet_catalog/orm.py`, in `SampleORM` next to `disk_size_bytes` (~line 56):

```python
# DB-only: relpath (under CATALOG_THUMBNAIL_DIR) of this sample's
# representative tomogram thumbnail, chosen by the scanner
# (thumbnails.representative_relpath). NULL when no tomogram thumbnail was
# generated. Used by GET /samples to build SampleSummary.thumbnail_path.
thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)
```

### Step 3 — drift-test carve-out

`tests/cryoet_catalog/test_orm_drift.py:46`:

```python
(Sample, orm.SampleORM, {"deleted_at", "disk_size_bytes", "thumbnail_path"}, {"sample_id"}),
```

### Step 4 — thumbnail generation module

New file `cryoet_catalog/thumbnails.py`. Keeps imaging out of the assembler and
mirrors how `discovery.dir_size_bytes` is a small scanner-called helper.

The module works on a **neutral projection** — `TomoRef(acquisition_id, kind,
tomogram_id, mrc_path)` tuples — so the same render+select logic serves both the
**upsert path** (projecting from `result.record`) and the **heal path**
(projecting from DB tomogram rows). `kind` is `"post"` or `"raw"`.

```python
"""Pre-generate tomogram center-slice thumbnails into a filesystem cache.

Writes one PNG per tomogram that has a readable mrc_path to
{root}/{sample_id}/{acquisition_id}/{tomogram_id}.png and returns the sample's
representative relpath for SampleORM.thumbnail_path.

numpy/matplotlib/mrcfile are imported lazily inside render so importing this
module stays cheap and the catalog env only pays for them when rendering.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)  # stdlib: loguru is API-only, not catalog

THUMBNAIL_WIDTH = 512


@dataclass(frozen=True)
class TomoRef:
    acquisition_id: str
    kind: str           # "post" or "raw"
    tomogram_id: str
    mrc_path: str | None


def _safe_segment(value: str) -> str:
    """Reject path-traversal in an id used as a path segment."""
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        raise ValueError(f"unsafe id segment: {value!r}")
    return value


def _relpath(sample_id: str, acquisition_id: str, tomogram_id: str) -> str:
    return "/".join((
        _safe_segment(sample_id),
        _safe_segment(acquisition_id),
        _safe_segment(tomogram_id) + ".png",
    ))


def _render_one(mrc_path: str, dest: Path) -> bool:
    from cryoet_catalog.imaging._mrc import render_center_xy_slice_png

    try:
        png = render_center_xy_slice_png(mrc_path, width=THUMBNAIL_WIDTH)
    except Exception as e:  # unreadable / non-volume MRC, etc.
        logger.warning("thumbnail render failed for %s: %s", mrc_path, e)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(png)
    tmp.replace(dest)  # atomic-ish; readers never see a half-written file
    return True


def generate_thumbnails(
    sample_id: str,
    tomos: list[TomoRef],
    thumbnail_root: Path,
    *,
    skip_existing: bool = False,
) -> str | None:
    """Render thumbnails for one sample's tomograms; return the representative
    relpath (post-then-raw, first acquisition with one), or None.

    ``skip_existing=False`` (upsert path) always re-renders — data changed.
    ``skip_existing=True`` (heal path) only renders missing files.
    Tomograms with no mrc_path (zarr-only) are skipped.
    """
    generated: dict[tuple[str, str], str] = {}  # (acq_id, kind) -> relpath
    # "post" before "raw" so a present post-processed thumbnail wins per acq.
    for ref in sorted(tomos, key=lambda r: (r.acquisition_id, r.kind != "post", r.tomogram_id)):
        if not ref.mrc_path:
            continue
        rel = _relpath(sample_id, ref.acquisition_id, ref.tomogram_id)
        dest = thumbnail_root / rel
        ok = True if (skip_existing and dest.is_file()) else _render_one(ref.mrc_path, dest)
        if ok:
            generated.setdefault((ref.acquisition_id, ref.kind), rel)

    return representative_relpath(generated)


def representative_relpath(generated: dict[tuple[str, str], str]) -> str | None:
    """Sample-level selection rule (Q4: fall through to the first acquisition
    that has a thumbnail). Isolated so a future 'representative tomogram' schema
    flag can replace just this function."""
    for acq_id in sorted({a for a, _ in generated}):
        rel = generated.get((acq_id, "post")) or generated.get((acq_id, "raw"))
        if rel:
            return rel
    return None


# ── Projections ────────────────────────────────────────────────────────────

def refs_from_record(record) -> list[TomoRef]:
    """Upsert-path projection from the assembled SampleRecord.

    record.acquisitions: dict[acq_id, AcquisitionFile] (assembler.py:186);
    each has .raw_tomogram (single|None) and .post_processed_tomogram (list),
    with .mrc_path populated by assembler.py:359-360.
    """
    refs: list[TomoRef] = []
    for acq_id, acq in record.acquisitions.items():
        for t in acq.post_processed_tomogram:
            refs.append(TomoRef(acq_id, "post", t.tomogram_id, t.mrc_path))
        if acq.raw_tomogram is not None:
            r = acq.raw_tomogram
            refs.append(TomoRef(acq_id, "raw", r.tomogram_id, r.mrc_path))
    return refs


def refs_from_db(session, sample_id: str) -> list[TomoRef]:
    """Heal-path projection from existing DB rows (no re-assembly)."""
    from cryoet_catalog import orm
    from sqlalchemy import select

    refs: list[TomoRef] = []
    for r in session.execute(
        select(orm.PostProcessedTomogramORM).where(
            orm.PostProcessedTomogramORM.sample_id == sample_id)
    ).scalars():
        refs.append(TomoRef(r.acquisition_id, "post", r.tomogram_id, r.mrc_path))
    for r in session.execute(
        select(orm.RawTomogramORM).where(
            orm.RawTomogramORM.sample_id == sample_id)
    ).scalars():
        refs.append(TomoRef(r.acquisition_id, "raw", r.tomogram_id, r.mrc_path))
    return refs
```

Confirm against real types when implementing: `AcquisitionFile` fields
`raw_tomogram` / `post_processed_tomogram` (`assembler.py:300-303`),
`record.acquisitions` shape (`assembler.py:186`), and that `mrc_path` is set by
`assembler.py:359-360`.

### Step 5 — wire generation into the scanner

**5a. `persistence.upsert_sample_record`** (`persistence.py:126`): add a
keyword param and inject, exactly like `disk_size_bytes`:

```python
def upsert_sample_record(
    session, record, *, extras, warnings, scan_run_id,
    disk_size_bytes: int | None = None,
    thumbnail_path: str | None = None,   # NEW
) -> None:
    ...
    sample_payload["deleted_at"] = None
    sample_payload["disk_size_bytes"] = disk_size_bytes
    sample_payload["thumbnail_path"] = thumbnail_path    # NEW
```

`_filter_to_columns` keeps it only because the ORM column now exists (Step 2).

**5b. `scanner._scan_one_sample`** (`scanner.py:147-213`): thread a
`thumbnail_dir: Path | None` param down from `scan_root` (`scanner.py:44-67`)
and add `from cryoet_catalog import thumbnails`.

*Upsert path* — next to the existing `disk_size = discovery.dir_size_bytes(...)`
(`scanner.py:191`), inside the transaction (Q3 — render inside; rollback just
leaves harmless orphan PNGs the next scan overwrites):

```python
disk_size = discovery.dir_size_bytes(sample_loc.path)
thumb_rel = None
if thumbnail_dir is not None:
    thumb_rel = thumbnails.generate_thumbnails(
        sample_loc.sample_id,
        thumbnails.refs_from_record(result.record),
        thumbnail_dir,
        skip_existing=False,          # data changed → always re-render
    )
persistence.upsert_sample_record(
    session, result.record,
    extras=result.extras, warnings=result.warnings,
    scan_run_id=scan_run_id,
    disk_size_bytes=disk_size,
    thumbnail_path=thumb_rel,          # NEW
)
```

*Skip path auto-heal (Q2)* — replace the bare `report.skipped += 1; return`
(`scanner.py:170-172`) with a cheap guard: one `stat` on the sample's stored
representative thumbnail; regenerate only if it's gone. Read the stored
`thumbnail_path` from the gating state already loaded
(`state.load_sample_state`) or via a tiny `session.get(orm.SampleORM, id)`:

```python
if thumbnail_dir is not None:
    stored = session.get(orm.SampleORM, sample_loc.sample_id)
    rel = stored.thumbnail_path if stored else None
    # rel is None  -> sample has no renderable tomogram; nothing to heal.
    # file present  -> steady state; one stat, done.
    if rel and not (thumbnail_dir / rel).is_file():
        with session.begin():                       # heal write txn
            new_rel = thumbnails.generate_thumbnails(
                sample_loc.sample_id,
                thumbnails.refs_from_db(session, sample_loc.sample_id),
                thumbnail_dir,
                skip_existing=True,                  # render only missing files
            )
            stored.thumbnail_path = new_rel
            session.add(stored)
        report.thumbnails_healed += 1
report.skipped += 1
report.skipped_ids.append(sample_loc.sample_id)
return
```

Add `thumbnails_healed: int = 0` to `ScanReport` (`scanner.py:26-41`) and print
it in `cli.py:_cmd_scan` alongside the other tallies. Note: steady-state cost is
one `session.get` + one `stat` per skipped sample; the render query/IO happens
only when the file is actually missing.

### Step 6 — config plumbing for `CATALOG_THUMBNAIL_DIR`

- **CLI** (`cli.py`): add `--thumbnail-dir` (default
  `os.environ.get("CATALOG_THUMBNAIL_DIR")`); in `_cmd_scan` resolve to a
  `Path` (create the dir if missing), pass `thumbnail_dir=` into
  `scanner.scan_root`. If unset, pass `None` (thumbnails simply not generated —
  scan still works).
- **`scanner.scan_root`**: add `thumbnail_dir: Path | None = None` param, pass
  through to `_scan_one_sample`.
- **API lifespan** (`api/main.py:_lifespan`): read `CATALOG_THUMBNAIL_DIR`; set
  `app.state.thumbnail_root = Path(raw).resolve()` if set, else `None`. Unlike
  `CATALOG_DATA_ROOT` this is **optional** (a missing/empty cache just yields
  placeholders), so don't hard-fail startup. Tests can pre-seed
  `app.state.thumbnail_root`.
- **`docker-compose.yml`**: add a named volume `thumbnails: {}`; mount
  `thumbnails:/thumbnails` (writable) in `scanner`, `thumbnails:/thumbnails:ro`
  in `api`; set `CATALOG_THUMBNAIL_DIR=/thumbnails` in both services' env.
- **`Dockerfile.scanner`**: add `CATALOG_THUMBNAIL_DIR=/thumbnails` to the `ENV`
  block (compose overrides anyway, but keep parity with `CATALOG_DB_URL`).
- **`.env` / `.env.example`**: document `CATALOG_THUMBNAIL_DIR`. Dev value
  (Q1): `CATALOG_THUMBNAIL_DIR=/groups/cryoet/cryoet/data/scratch/thumbnails`
  — a sibling of `CATALOG_DATA_ROOT` (`.../scratch/data`), **not** inside it, so
  the scan and `dir_size_bytes` walk never see the cache.
- **`.gitignore`**: add `*.png.tmp` (and `thumbnails/` in case anyone points the
  dev dir at the repo root) so stray cache artifacts aren't committed.
- **`README.md`**: document `CATALOG_THUMBNAIL_DIR`, that a plain rescan
  auto-heals a wiped cache, and that `--force` fully rebuilds it.

### Step 7 — API: serving route + list endpoint field

**7a. New `cryoet_catalog/api/routes/thumbnails.py`:**

```python
@router.get("/{relpath:path}")
async def get_thumbnail(relpath: str, request: Request):
    root = getattr(request.app.state, "thumbnail_root", None)
    if root is None:
        raise HTTPException(404, "thumbnails not configured")
    try:
        resolved = (root / relpath).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "thumbnail not found")
    if not resolved.is_relative_to(root) or resolved.suffix != ".png":
        raise HTTPException(404, "thumbnail not found")
    return Response(
        content=resolved.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
```

(Consider `FileResponse` instead of `read_bytes` for streaming; either is fine
at thumbnail sizes. Mirror the path-containment check from
`path_validation.validate_under_data_root` but against `thumbnail_root`.)

Register in `api/main.py:create_app`:
`app.include_router(thumbnails.router, prefix="/thumbnails", tags=["thumbnails"])`
and add `thumbnails` to the `routes` import tuple.

**7b. `schemas.py:SampleSummary`** — add:

```python
thumbnail_path: str | None = None  # relpath under the thumbnail cache; None if absent
```

**7c. `samples.py:list_samples`** — add `orm.SampleORM.thumbnail_path` to the
SELECT (`samples.py:151-161` returns `orm.SampleORM` already, so it's on
`r[0]`), and set it in the `SampleSummary(...)` construction
(`samples.py:311-326`): `thumbnail_path=r[0].thumbnail_path`.

### Step 8 — migration for existing on-disk DBs

- New / test DBs: nothing (create_all picks up `thumbnail_path`).
- Existing DBs: `ALTER TABLE samples ADD COLUMN thumbnail_path VARCHAR;`
  (then a `--force` rescan to populate + build the cache).

### Step 9 — Frontend wiring

Add a shared helper (e.g. in `Thumbnail.tsx` or a small `thumbnails.ts`):

```ts
// Relpath scheme must match cryoet_catalog/thumbnails._relpath.
export function tomogramThumbnailUrl(s: string, a: string, t: string): string {
  const enc = (x: string) => x.split('/').map(encodeURIComponent).join('/')
  return `/api/thumbnails/${enc(s)}/${enc(a)}/${enc(t)}.png`
}
export function thumbnailUrl(relpath?: string | null): string | null {
  return relpath ? `/api/thumbnails/${relpath.split('/').map(encodeURIComponent).join('/')}` : null
}
// Acquisition representative: post[0] then raw.
export function acquisitionRepTomogramId(a: AcquisitionOut): string | null {
  return a.post_processed_tomograms[0]?.tomogram_id ?? a.raw_tomogram?.tomogram_id ?? null
}
```

Wire the four call sites:

1. **`TomogramsAnnotationsTable.tsx`** (`:54-62`, `:154-171`): change
   `tomogramPreviewSrc` to `tomogramThumbnailUrl(sampleId, acqId, tomoId)`
   (cached) instead of the `/preview.png` URL. 404→placeholder is automatic.
2. **`SampleAcquisitionsTable.tsx`** (`:16-29`, `:40-53`): replace
   `acquisitionPreviewSrc` (currently the **tilt-series** preview) with:
   resolve `acquisitionRepTomogramId(row.original)`; if non-null,
   `tomogramThumbnailUrl(sampleId, acq_id, repId)`, else `null` (placeholder).
3. **`samples.$sampleId.tsx`** (`:140`): replace the hero
   `<ThumbnailPlaceholder width="100%" height={220} />` with a `PreviewThumbnail`
   whose `src` = first acquisition's representative tomogram thumbnail
   (`sample.acquisitions` sorted by `acquisition_id`, first with a rep id →
   `tomogramThumbnailUrl`), `null` → placeholder. Keep `width="100%" height={220}`.
4. **`SamplesPortalTable.tsx`** (`:23-28`): replace the placeholder Cell with
   `<PreviewThumbnail src={thumbnailUrl(row.original.thumbnail_path)} />`
   (needs `thumbnail_path` added to the `SampleSummary` TS type in
   `frontend/src/types` — mirror Step 7b).

Leave `acquisitions.$acquisitionId.tsx:118` (tilt-series hero) unchanged.

## Tests

- **`tests/cryoet_catalog/test_orm_drift.py`** — carve-out edit (Step 3); the
  test enforces it.
- **New `tests/cryoet_catalog/test_thumbnails.py`** — unit tests for the
  generation module with a tiny synthetic MRC fixture (reuse whatever MRC
  fixture `test_assembler`/`imaging` tests use; or write a 1-frame mrcfile):
  - `generate_thumbnails` writes a PNG at the deterministic relpath; bytes start
    with the PNG magic; returns the representative relpath.
  - `representative_relpath(generated)`: post beats raw within an acq; raw used
    when no post; **falls through** to a later acq when the first has none;
    `None` for an empty dict.
  - `skip_existing=True` doesn't re-render when the file already exists, but does
    render a missing one.
  - `_safe_segment` rejects `..` / `/` / empty.
  - `TomoRef` with `mrc_path=None` (zarr-only) → skipped, no file, no rep.
  - re-render overwrites in place (no `.tmp` left behind).
- **`tests/cryoet_catalog/test_scanner.py`** — after scanning a fixture tree
  with `thumbnail_dir` set: `SampleORM.thumbnail_path` populated and the file
  exists on disk; `force=True` re-renders; `thumbnail_dir=None` ⇒ scan succeeds,
  `thumbnail_path` NULL, no files written. **Auto-heal (Q2):** scan once, delete
  the cache dir, scan again *without* `--force` ⇒ the gated sample is still
  counted skipped but its representative thumbnail file is recreated and
  `thumbnails_healed` is incremented; a skip with the file still present does
  *not* re-render (assert mtime unchanged).
- **`tests/cryoet_catalog/test_persistence.py`** — `upsert_sample_record(...,
  thumbnail_path="x/y/z.png")` writes it; default (omitted) writes NULL.
- **New `tests/cryoet_catalog/test_api_thumbnails.py`** — with a pre-seeded
  `app.state.thumbnail_root` containing a known PNG: 200 + `image/png` for an
  existing relpath; 404 for missing; 404 for `../` traversal attempts; 404 when
  `thumbnail_root` is `None`.
- **`tests/cryoet_catalog/test_api_samples.py`** (list endpoint) — seed
  `SampleORM.thumbnail_path` and assert it round-trips into
  `SampleSummary.thumbnail_path`; NULL stays `None`.
- **Frontend** — if there are component tests, assert the row `<img src>` matches
  the `/api/thumbnails/...` scheme and that a null rep yields the placeholder.
  (Confirm whether the frontend has a test harness; otherwise manual check.)

Run (confirm exact env/command from repo conventions first):

```
pixi run -e catalog pytest tests/cryoet_catalog/test_thumbnails.py \
  tests/cryoet_catalog/test_scanner.py tests/cryoet_catalog/test_persistence.py \
  tests/cryoet_catalog/test_orm_drift.py
pixi run -e api pytest tests/cryoet_catalog/test_api_thumbnails.py \
  tests/cryoet_catalog/test_api_samples.py
```

## Risks & mitigations

- **Scanner can't import `imaging._mrc` without the new deps.** Mitigated by
  Step 1 + lock refresh; the generation module imports imaging lazily and
  guards the whole thing behind `thumbnail_dir is not None`, so a scanner env
  *without* the deps still scans (just skips thumbnails) as long as
  `CATALOG_THUMBNAIL_DIR` is unset.
- **Longer per-sample transaction** (render is heavy). Mitigated: only on the
  non-skip path (changed samples / `--force`), same model as `disk_size`; single
  writer + WAL means readers aren't blocked (Q3 — render inside the txn).
- **Stale cache when only non-parse-target files change.** A change to a
  non-parse-target file won't re-render until the next parse-target change or
  `--force`. Accepted (same staleness model as `disk_size_bytes`). A *wiped*
  cache, by contrast, is auto-healed on the next plain scan (Q2, Step 5b).
- **Path traversal via ids in the serving route or filename.** Mitigated by
  `_safe_segment` on write and the `is_relative_to(root)` + `.png` check on read.
- **Read-only data root.** Addressed by the dedicated `thumbnails` volume.
- **Two MRC decodes (scan render + existing on-the-fly `preview.png`).** We keep
  both for now; if `preview.png` is truly unused after Step 9 we can delete it in
  a follow-up.
- **`SampleSummary.thumbnail_path` points at a file that was later deleted**
  (cache blown away without rescan) → the browse-page `<img>` 404s →
  placeholder. Acceptable (graceful).

## Resolved decisions (was: open questions)

1. **Cache location.** Pure config via `CATALOG_THUMBNAIL_DIR`. Dev →
   `/groups/cryoet/cryoet/data/scratch/thumbnails` (sibling of the test data,
   outside `CATALOG_DATA_ROOT`). Prod (k8s) → a mounted volume (modeled by the
   compose `thumbnails` volume). No code difference between environments.
2. **Rebuild after wipe → auto-heal on a plain scan.** Skip path does one
   `stat`; regenerates from DB rows only when the representative file is missing
   (Step 5b). The k8s CronJob self-heals a lost volume; `--force` still does a
   full rebuild.
3. **Render inside the per-sample transaction.** Single writer + WAL ⇒ no reader
   blocking; a rollback leaves only harmless orphan PNGs.
4. **Sample selection falls through** to the first acquisition that *has* a
   thumbnail (not strictly the first acquisition). Maximizes coverage; isolated
   in `representative_relpath` for the future "representative tomogram" flag.
5. **Image params:** width 512px, percentile (1, 99), no height cap (CSS
   `object-fit`).
6. **MRC-only generation** (data is mostly MRC). Zarr-only tomograms →
   placeholder; a zarr center-slice renderer is deferred.
7. **`SampleSummary.thumbnail_path` carries the relpath**; the frontend prefixes
   `/api/thumbnails/`, keeping the API ignorant of the proxy prefix.

## Remaining follow-ups (non-blocking)

- Partial cache loss (representative file present but a sibling tomogram's PNG
  missing) isn't healed until the next parse-target change or `--force`; the
  per-tomogram 404→placeholder covers it visually in the meantime.
- If `preview.png` proves unused after Step 9, remove the on-the-fly tomogram
  preview endpoint in a follow-up.
- Future: add the `representative_tomogram` schema flag and switch
  `representative_relpath` to honor it.
