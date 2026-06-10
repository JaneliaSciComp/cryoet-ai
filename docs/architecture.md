# How the four layers fit together

The repo is a **one-way data pipeline**: filesystem → SQLite → HTTP → browser. Each layer is decoupled from the next by a stable boundary (the DB, the API contract), so they can be developed and tested in isolation.

```
   ┌────────────────────────────────────────────────┐
   │ Sample directory tree on disk                  │
   │   sample.toml, acquisition.toml, *.mdoc, *.mrc │
   │   *.zarr, processing folder names              │
   └───────────────────────┬────────────────────────┘
                           │  walks tree
                           ▼
   ┌────────────────────────────────────────────────┐
   │ SCANNER  (src/catalog/, run via CLI)        │
   │  • discovery.py     — find samples/files       │
   │  • parsers/         — TOML, MDOC, MRC, OME-Zarr│
   │  • assembler.py     — merge into SampleRecord  │
   │  • state.py         — mtime gating             │
   │  • persistence.py   — idempotent upsert, prune │
   │  • scanner.py       — orchestrates above       │
   └───────────────────────┬────────────────────────┘
                           │  SQLAlchemy writes
                           ▼
   ┌────────────────────────────────────────────────┐
   │ SQLite DB  (catalog.db)                 │
   │  samples, acquisitions, tomograms, annotations,│
   │  chromatin, synapse, simulation, freezing,     │
   │  milling, aunp, extras,                        │
   │  scans, scan_state, scan_warnings, catalog_meta│
   └───────────────────────┬────────────────────────┘
                           │  read-only SELECTs
                           ▼
   ┌────────────────────────────────────────────────┐
   │ API  (src/catalog/api/, FastAPI on :8000)   │
   │  GET /samples            — list / detail       │
   │  GET /samples/{id}/warnings                    │
   │  GET /scans              — scan run history    │
   │  GET /extras             — unknown TOML keys   │
   └───────────────────────┬────────────────────────┘
                           │  fetch() + TanStack Query
                           ▼
   ┌────────────────────────────────────────────────┐
   │ UI  (frontend/, TanStack Start + MUI on :3000) │
   │  SSR loaders → API direct (:8000)              │
   │  Browser fetches → /api/* (Vite proxy)         │
   │  Routes:                                       │
   │    /          — landing                        │
   │    /samples   — table of samples + warnings    │
   └────────────────────────────────────────────────┘
```

## Layer-by-layer summary

### Scanner

One scan = one transactional walk of a data root, invoked via `python -m catalog scan <root>`. Each invocation is recorded in the `scans` table; warnings and field conflicts flow into `scan_warnings`. The single-writer contract means only one scan should run against a given DB at a time.

| Step | What happens | Where to look |
|---|---|---|
| 1. CLI entry | Parses flags (`--force`, `--prune`, `--on-voxel-mismatch`, …) and constructs the engine. | `src/catalog/cli.py` |
| 2. Walk root | `iter_samples` enumerates sample directories under the root. | `src/catalog/discovery.py` |
| 3. Gating | For each sample, compare current file mtimes + parse-target set against `scan_state`; skip if unchanged (unless `--force`). | `src/catalog/state.py` |
| 4. Parse | Extract fields from each source (TOML, MDOC, MRC header, OME-Zarr, frame extension, folder names). | `src/catalog/parsers/` |
| 5. Assemble | Merge parser outputs into a validated `SampleRecord`; collect warnings + field conflicts. | `src/catalog/assembler.py` |
| 6. Persist | Idempotent upsert of sample + acquisitions + tomograms + annotations + side tables + extras. | `src/catalog/persistence.py` |
| 7. Prune (optional) | Soft-delete samples missing from disk, with safety-floor guard. | `src/catalog/persistence.py` |
| 8. Orchestrate | Drives steps 2–7 inside per-sample transactions and writes the `scans` row. | `src/catalog/scanner.py` |

### Database

Plain SQLite via SQLAlchemy. The schema mirrors the Pydantic record: one row per sample/acquisition/tomogram/annotation, side tables for the conditional blocks (`chromatin`, `synapse`, `simulation`, …), an `extras` table for un-schemaed TOML keys, and bookkeeping tables for scan history and gating state. The DB is the **only** contract between the writer (scanner) and readers (API, ad-hoc SQL).

| Step | What happens | Where to look |
|---|---|---|
| 1. Engine + URL | `make_engine` builds a SQLAlchemy engine; default URL is `sqlite:///catalog.db`. | `src/catalog/db.py` |
| 2. Schema init | `init_schema` creates tables idempotently on first use. | `src/catalog/db.py` |
| 3. Core entity tables | `samples`, `acquisitions`, `tomograms`, `annotations` mirror the Pydantic schema. | `src/catalog/orm.py` |
| 4. Side tables | One row per sample for optional blocks: `chromatin`, `synapse`, `simulation`, `freezing`, `milling`, `aunp`. | `src/catalog/orm.py` |
| 5. Extras | Captures un-schemaed TOML keys without losing them. | `src/catalog/orm.py` |
| 6. Scan bookkeeping | `scans` (run history), `scan_state` (mtime gating), `scan_warnings`, `catalog_meta`. | `src/catalog/orm.py`, `src/catalog/state.py` |

### API

FastAPI app, **read-only**, no auth. Configured via `CATALOG_DB_URL` (defaults to `sqlite:///catalog.db`) and `CORS_ORIGINS` (defaults to `http://localhost:5173`). The lifespan hook builds one engine per process; tests pre-seed `app.state.engine` to point at a fixture DB.

| Step | What happens | Where to look |
|---|---|---|
| 1. App factory + CORS | Creates the FastAPI app, parses CORS origins, registers routers. | `src/catalog/api/main.py` |
| 2. Engine lifespan | Builds the engine on startup, disposes it on shutdown; respects pre-seeded test engines. | `src/catalog/api/main.py` |
| 3. Session dependency | Per-request SQLAlchemy session injected into route handlers. | `src/catalog/api/deps.py` |
| 4. Response schemas | Pydantic models that shape JSON responses. | `src/catalog/api/schemas.py` |
| 5. `/samples` | List and detail endpoints for samples, acquisitions, tomograms, annotations. | `src/catalog/api/routes/samples.py` |
| 6. `/scans` | Scan run history. | `src/catalog/api/routes/scans.py` |
| 7. `/samples/{id}/warnings` | Per-sample warnings collected by the scanner. | `src/catalog/api/routes/warnings.py` |
| 8. `/extras` | Un-schemaed TOML keys captured during scan. | `src/catalog/api/routes/extras.py` |

### UI

TanStack Start (full-stack React framework on Vite) + React 19 + TypeScript + Material UI (with Emotion). TanStack Router provides file-based routing with SSR data loaders; TanStack Query handles client-side fetching/caching. Today there's a single meaningful page — `/samples` — which renders a table of samples and warning counts.

The dev server runs on `:3000` (bound on all interfaces for the dev-container port-forward) and proxies `/api/*` to FastAPI on `:8000`. Route loaders run during SSR in Node and bypass the proxy by fetching `http://localhost:8000` directly — `import.meta.env.SSR` toggles between the two base URLs.

| Step | What happens | Where to look |
|---|---|---|
| 1. Dev server + proxy | Vite serves on :3000 and proxies `/api/*` to :8000; SSR `noExternal` keeps MUI bundled. | `frontend/vite.config.ts` |
| 2. SSR entry | Server entry that renders the router for each request. | `frontend/src/ssr.tsx` |
| 3. Client entry | Hydrates the SSR-rendered router in the browser. | `frontend/src/client.tsx` |
| 4. Router factory | Builds the router with a fresh `QueryClient` per request. | `frontend/src/router.tsx` |
| 5. Route tree | Generated route registry (auto-managed by the TanStack Start plugin). | `frontend/src/routeTree.gen.ts` |
| 6. Root document | HTML shell, Emotion `CacheProvider`, MUI `ThemeProvider` + `CssBaseline`, React Query provider, shared `Header`. | `frontend/src/routes/__root.tsx` |
| 7. Theme | Material UI theme definition. | `frontend/src/setup/theme.ts` |
| 8. Shared components | `Header`, `CustomLink`, `CustomButtonLink`, `Counter`. | `frontend/src/components/` |
| 9. Landing page | Index route. | `frontend/src/routes/index.tsx` |
| 10. Samples page | SSR `loader` calls `/samples`, renders an MUI-styled table. | `frontend/src/routes/samples.tsx` |

## Why the split

- **Scanner ↔ DB** is the slow, I/O-heavy boundary; mtime gating means re-scans cost ~one stat per file rather than re-parsing everything.
- **DB ↔ API** keeps the API stateless and trivially reproducible — point any read tool (the UI, `sqlite3`, a notebook) at the same file.
- **API ↔ UI** lets the UI iterate independently of the scanner and be deployed as static assets later.
