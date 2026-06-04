# CryoET + AI Data Portal

A Pydantic-validated metadata schema, a directory-walking catalog scanner, a FastAPI read API, and a TanStack Start + Material UI frontend for the CryoET + AI project. The portal answers one question across both the experimental and simulation arms of the project: **which conditions have we covered, and which still need cryoET imaging, simulation, or both?**

> **Status: draft / proposed.** Schema fields and conventions are still evolving as researchers start authoring metadata against it.

---

## Repository map

| Path | Contents |
|---|---|
| `cryoet_schema/` | Authoritative Pydantic schema, JSON Schema generators, and the `validate` CLI. |
| `cryoet_catalog/` | Directory-walking scanner that builds the catalog DB from `sample.toml` + `acquisition.toml` + MDOC/MRC headers. Includes the FastAPI read API under `cryoet_catalog/api/`. |
| `frontend/` | React + TanStack Start + Material UI app that reads from the FastAPI server. |
| `templates/` | Starter `sample.toml`, `acquisition.toml`, and directory skeletons, containing the TOML files in the expected locations, for new experimental (cryoET) and simulation (MD + synthetic cyroET) samples. |
| `docs/data_organization.md` | The on-disk layout and TOML metadata authoring guide for researchers. |
| `docs/architecture.md` | System architecture overview. |
| `.claude/plans/` | Implementation plans, including the catalog scanner plan. |
| `pyproject.toml` / `pixi.lock` | PyPI dependencies (`[project]`), and pixi config (`[tool.pixi.*]`). |

For the schema itself, see `cryoet_schema/schema_info.md` (human reference) and `cryoet_schema/schema.py` (Pydantic source of truth).

---

## Setup

**Note:** This setup guide assumes you are working on machine with access to the Janelia file system.

1. [Install pixi](https://pixi.prefix.dev/latest/installation/).
2. From the repo root, run `pixi install` to materialize the Python environments.

The frontend's Node deps are installed automatically the first time you run `pixi run frontend` (and re-run only when `package.json` / `package-lock.json` change). You don't need a separate `npm install` step.

3. Create the database. Pass the path to the data root via the CATALOG_DATA_ROOT env variable. This will scan the samples at that path and create a SQLite database called `cryoet_catalog.db` in your repo root.

```
CATALOG_DATA_ROOT=/path/to/data pixi run scan --init
```

---

## Running the app

The portal has two processes: the FastAPI backend (reads the catalog DB) and the TanStack Start frontend (server-renders + hydrates a React app, proxying `/api` to FastAPI). Run them in two terminals.

**Terminal 1 — API:**
```
pixi run api
```
Serves `http://localhost:8000` with auto-reload. Swagger UI at `/docs`.

**Terminal 2 — Frontend:**
```
pixi run frontend
```
Open the data portal at `http://localhost:3000`.

### Alternate port

If port 8000 is taken, pass uvicorn flags through to use an alternate port. You can also change the IP binding:
```
pixi run api --host 0.0.0.0 --port 8034
```

If you change the backend host/port, you will also need to point the frontend to it. The frontend reads its dev-server settings from `frontend/.env.local` (gitignored). Create it like this:

```
# Backend the /api proxy points to (default: http://localhost:8000)
API_PROXY_TARGET=http://localhost:8034

# Port the Vite dev server listens on (default: 3000)
FRONTEND_PORT=3030
```

---

## Schema authoring & validation

For researchers writing `sample.toml` / `acquisition.toml`, the authoring guide is in **[`docs/data_organization.md`](docs/data_organization.md)**. Quick commands:

| Command | What it does |
|---|---|
| `pixi run validate {sample_dir}` | Validate `sample.toml` and all `acquisition.toml` files under a sample directory. |
| `pixi run json-schema` | Regenerate `cryoet_schema/schema.json` and `acquisition.schema.json` from the Pydantic models. Run after any change to `schema.py`. |
| `pixi run test` | Run the test suite. |

---

## Further reading

- **[`docs/data_organization.md`](docs/data_organization.md)** — directory layout, metadata files, schema rules, researcher workflow.
- **[`docs/architecture.md`](docs/architecture.md)** — system architecture.
- **`cryoet_schema/schema_info.md`** — every field that lands in the portal DB, grouped by entity, with the source of each (TOML / MDOC / MRC / directory / derived).
