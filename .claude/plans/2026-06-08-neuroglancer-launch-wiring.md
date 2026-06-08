# Neuroglancer launch: wire the in-process viewer (aicryoet-tools method)

**Date:** 2026-06-08
**Status:** proposed

## Context

The portal wants a working "View in Neuroglancer" button on tomograms (and
tilt-series). Two strategies exist:

1. **In-process LocalVolume server** (the `aicryoet-tools` prototype method):
   the API reads the MRC into a numpy array, spins up a process-global
   Neuroglancer Python server, exposes the array as a `LocalVolume`, and hands
   the browser a viewer URL (`python://volume/<hash>`). The browser talks to
   that live Python server. Works for **any format the Python loader supports
   (including `.mrc`)**, because decoding happens server-side.

2. **Frontend URL construction against a zarr** (the eventual target): the
   browser's Neuroglancer client reads an HTTP-accessible OME-Zarr directly
   (e.g. a Fileglancer data link, `...|zarr3:`). No backend launch, no Python
   server, no volume held in RAM. Only works for data already in a
   browser-readable chunked format (zarr/n5/precomputed) — **not `.mrc`**.

This plan implements **strategy 1 now** while structuring the frontend so that
**strategy 2 is a later call-site swap, not a rewrite**.

### What already exists (backend — effectively complete)

The `2026-05-08-dashboard-mvp.md` plan (§7.4) already built the backend:

- `cryoet_catalog/imaging/_neuroglancer.py` — `view_neuroglancer()` (vendored
  from `aicryoet-tools` commit `083ccec`: X/Y IMOD flip, central-subvolume
  percentile contrast, `LocalVolume`) + `neuroglancer_url()` with a
  `DASHBOARD_HOSTNAME` override.
- `cryoet_catalog/imaging/_mrc.py:101` — `read_mrc_volume()` returns
  `(data, voxel_size, axis_order)` ready for the viewer.
- `POST /tomograms/{sample_id}/{acquisition_id}/{tomogram_id}/neuroglancer`
  (`api/routes/tomograms.py:156`) → `ViewerLaunchOut { url }`. Registered in
  `api/main.py:195`. Tilt-series has the analogous endpoint
  (`api/routes/tilt_series.py:234`, registered at `main.py:196`).
- Bounded LRU viewer registry at `app.state.active_viewers`
  (`NEUROGLANCER_MAX_VIEWERS`, default 8), guarded by an `asyncio.Lock`, launch
  wrapped in `run_in_threadpool` — `api/main.py:163`,
  `api/routes/tomograms.py:111`.
- Path validation against `app.state.data_root_resolved`.
- `neuroglancer >=2.40` is a declared dep (`pyproject.toml:79`, `[tool.pixi
  .feature.api.dependencies]`).

### The gap (frontend + deployment)

- `frontend/src/components/common/NeuroglancerButton.tsx` is a presentational
  stub: it takes a `url` prop and renders **disabled** when `null`. Both call
  sites in `TomogramsAnnotationsTable.tsx` pass `url={null}` (lines 110, 195).
- No `useMutation` exists anywhere in the frontend yet (only
  `QueryClientProvider` is wired in `__root.tsx:43`).
- The dev `api` task runs `uvicorn ... --reload` (`pyproject.toml:87`), which is
  **incompatible** with the in-process Neuroglancer server (binds one HTTP
  server per process; reload's second launch fails).
- The container deployment exposes **only nginx:80** (`docker-compose.yml`,
  `nginx.conf`). The API container has no published ports, and the
  Neuroglancer server binds a *separate* port. The browser cannot reach it.
  **This is the central deployment problem** (see §Deployment).

## Goals

1. Make "View in Neuroglancer" functional for **tomograms** via the existing
   backend launch endpoint, in both **dev** and the **container/k8s**
   deployment (via a pinned, published Neuroglancer port — goal 4).
2. Implement the client launch flow faithfully to the prototype: synchronous
   popup → POST → hostname rewrite → navigate.
3. Structure `NeuroglancerButton` around a **swappable URL-source strategy** so
   the future zarr/Fileglancer path is a call-site change.
4. Fix the dev `api` task to `--no-reload`, and make the Neuroglancer server
   reachable in the **container/k8s** deployment by pinning its port and
   publishing it (decided 2026-06-08).

### Non-goals

- Tilt-series button wiring (**fast-follow**, decided 2026-06-08): the endpoint
  exists and the shared button supports `entity: 'tilt-series'`; only the
  call-site wiring is deferred so this plan stays focused on tomograms.
- Annotation-row launches (no annotation endpoint exists; those rows stay
  disabled).
- The zarr/Fileglancer frontend URL construction itself (strategy 2). This plan
  only leaves the seam for it.

## Implementation steps

### 1. Frontend: a swappable-source `NeuroglancerButton`

Replace the `url`-prop stub with a presentational button driven by a
discriminated `source` prop, so the "how do I get a URL" strategy is injected:

```ts
type NeuroglancerSource =
  // Strategy 1 (now): POST to the backend launch endpoint.
  | { kind: 'launch'; entity: 'tomogram' | 'tilt-series';
      sampleId: string; acquisitionId: string; entityId: string }
  // Strategy 2 (later): construct the URL on the client from a zarr data link.
  | { kind: 'zarr-link'; url: string }
  // No viewable source — render disabled.
  | null
```

- Keep the disabled + tooltip rendering for `source == null` (annotation rows,
  rows with neither `mrc_path` nor a future zarr link).
- For `kind: 'zarr-link'`, the URL is already known → behave like the current
  `href` button (open in new tab). This is the seam the later work fills.
- For `kind: 'launch'`, run the launch flow (step 2). All three paths end in
  "open a URL in a new tab," so the button's visual surface never changes when
  strategy 2 lands.

### 2. Frontend: the launch flow (client-only mutation)

Implement inside `NeuroglancerButton` (decision §11.20 of the MVP plan: launch
is **client-only**, never from an SSR loader):

- Add `launchNeuroglancer(source)` helper that POSTs via the existing
  `apiFetch` (`frontend/src/utils/api.ts`) to
  `/tomograms/${sampleId}/${acquisitionId}/${entityId}/neuroglancer` (or
  `/tilt-series/...`), typed to `ViewerLaunchOut` (`{ url: string }`).
- Use `useMutation` from `@tanstack/react-query`.
- On click (the prototype's anti-popup-blocker dance, mirrors
  `aicryoet-tools/.../cryoet.py:1145`):
  1. Synchronously `const w = window.open('about:blank', '_blank')` inside the
     click handler (user gesture).
  2. `await` the mutation.
  3. **Hostname rewrite**: `const u = new URL(data.url); u.hostname =
     window.location.hostname; w.location = u.toString()`. Guard with
     `typeof window !== 'undefined'`. The backend reports its own host; the
     rewrite points the browser at the host it already trusts. (Note: the
     backend also supports a `DASHBOARD_HOSTNAME` override; the client rewrite
     is the chosen mechanism — do not rely on both.)
  4. On error: `w?.close()` and surface a toast/inline error; reset button.
- Button shows a loading state (disabled + spinner) while the mutation is
  in-flight.

### 3. Frontend: wire the call sites

In `frontend/src/components/acquisitions/TomogramsAnnotationsTable.tsx`:

- **Tomogram rows** (line ~195): pass
  `source={{ kind: 'launch', entity: 'tomogram', sampleId,
  acquisitionId: acquisition.acquisition_id, entityId: row.original.tomogram_id }}`
  when `row.original.mrc_path` is non-null; otherwise `source={null}`.
- **Annotation rows** (line ~110): keep `source={null}` (no endpoint).
- Confirm `mrc_path` is present on the row type used by the table
  (`TomogramOutBase.mrc_path` exists in `types.ts:95`); thread it into the
  `TomogramRow` shape built by `combinedTomograms` if not already carried.

Add a `ViewerLaunchOut` type to `frontend/src/types.ts` (`{ url: string }`).

### 4. Backend: dev-task + small confirmations

- Change the dev `api` task in `pyproject.toml:87` to `uvicorn
  cryoet_catalog.api.main:app --no-reload --port 8000` (decided 2026-06-08 —
  launches are a first-class feature, so the default task must work with them).
  The MVP plan (§11.9) requires single-worker, no-reload for Neuroglancer; the
  current `--reload` default silently breaks the second launch. Note the loss
  of hot-reload in the README's "Running the app" section.
- Confirm `app.state` Neuroglancer registry init runs unconditionally in
  lifespan (`main.py:163`) — it does.
- No new endpoint work; the route, schema, registry, and path validation are
  all present.

### 5. Deployment plumbing (fix + publish the Neuroglancer port)

See §Deployment for the analysis. The Neuroglancer server is process-global and
serves all viewers from **one** port (URLs are `http://host:port/v/<token>/`
with state in the `#!` fragment), so a single pinned, published port suffices.

- **Pin the port**: extend `_ensure_bind_address()` in
  `cryoet_catalog/imaging/_neuroglancer.py:33` to pass a fixed port —
  `neuroglancer.set_server_bind_address(bind_address, bind_port=<port>)` — read
  from a new `NEUROGLANCER_PORT` env var (default e.g. `8050`).
  - **Prerequisite (verify first)**: confirm `set_server_bind_address` accepts
    `bind_port` in the pinned `neuroglancer >=2.40` build (the pixi env was not
    materializable during planning). If the kwarg differs, use the equivalent
    (`neuroglancer.server.global_server_args` / `bind_port`) the installed
    version exposes. This is a hard prerequisite for the publish step below.
- Keep `NEUROGLANCER_BIND_ADDRESS=0.0.0.0` so the viewer server is reachable
  off-host (default in `_neuroglancer.py:40`).
- **Publish the port (compose)**: add `NEUROGLANCER_PORT` to the `api` service
  `environment` in `docker-compose.yml` and publish it under `ports:` (e.g.
  `"8050:8050"`). nginx is *not* used for this — Neuroglancer serves its
  assets/data at the server root, so subpath-proxying is impractical; the
  browser hits `host:8050` directly, with the client hostname rewrite (step 2)
  pointing it at the right host.
- **Publish the port (k8s)**: add the pinned port to the `api` Service /
  container port list so it is routable from the browser. (TLS for that port is
  a deployment concern for the cluster router; flag to ops.)
- **Hostname/host reachability**: the client hostname rewrite (step 2) assumes
  the Neuroglancer host is the same host the browser used for the app. Where
  that does not hold, `DASHBOARD_HOSTNAME` overrides the host server-side.
- Document in `README.md`: the **`--no-reload` / single-worker** requirement,
  the new `NEUROGLANCER_PORT`, and that the Neuroglancer server listens on that
  *separate published port* (not behind nginx).
- Document env vars: `NEUROGLANCER_BIND_ADDRESS`, `NEUROGLANCER_PORT`,
  `NEUROGLANCER_MAX_VIEWERS`, `DASHBOARD_HOSTNAME` (the last three are already
  consumed by the backend; currently undocumented).

### 6. Tests

- Backend: the MVP plan already specifies `test_api_neuroglancer.py` (smoke +
  bounded-LRU eviction + concurrent-launch race). Confirm it exists and passes;
  add if missing.
- Frontend: a component test for `NeuroglancerButton` covering: `source==null`
  → disabled; `kind:'zarr-link'` → anchor with the given href;
  `kind:'launch'` → click opens a window, calls the mutation, and rewrites the
  hostname (mock `window.open` + `apiFetch`).

## Deployment (fix + publish the Neuroglancer port)

The in-process method needs the browser to reach the Neuroglancer HTTP server,
which is a **process-global server on its own port**, distinct from the API's
8000. All viewers share that one server (URLs are `http://host:port/v/<token>/`
with state in the `#!` fragment), so a single reachable port suffices.

**Decision (2026-06-08): pin the Neuroglancer port and publish it** rather than
deferring to zarr-only for production. Mechanics:

- The port is pinned via `set_server_bind_address(..., bind_port=NEUROGLANCER_PORT)`
  (default `8050`) — see step 5, including the prerequisite to verify the kwarg
  in the installed build.
- The `api` service publishes that port in `docker-compose.yml`, and the k8s
  `api` Service/container exposes it. The browser hits `host:<NEUROGLANCER_PORT>`
  directly — **not** through nginx, since Neuroglancer serves assets/data at the
  server root and cannot be subpath-proxied.
- The client hostname rewrite (step 2) points the browser at the host it used
  for the app; `DASHBOARD_HOSTNAME` overrides server-side where that fails.

- **Dev / two-terminal / single workstation**: same mechanism, simpler — the API
  runs on a reachable host with `0.0.0.0` bind; the browser reaches
  `host:<NEUROGLANCER_PORT>` directly after the rewrite. Matches how the
  `aicryoet-tools` prototype runs.

Strategy 2 (zarr via Fileglancer) remains the longer-term direction and can
later supersede the published port entirely (see §The strategy-2 swap seam), but
this plan makes the in-process launch work in the real container/k8s deployment.

## The strategy-2 swap seam (why this is forward-compatible)

The data model already carries the zarr signal: `zarr_path`, `zarr_axes`,
`zarr_scale` exist on every tomogram output (`types.ts:96–98`,
`orm.py:282/310/361`). When strategy 2 is built:

- Add a client helper that builds the `#!`-encoded Neuroglancer state from a
  Fileglancer data link — the pieces already exist: `utils/fileglancer.ts`
  (`toFileglancerUrl`) for the share-path mapping, plus the JSON-state shape
  (named `z/y/x` dims + `"m"` units, `shaderControls.normalized.range`,
  `layout`). Append `|zarr3:` to the data-link URL as the layer `source`.
- Flip the call sites from `{ kind: 'launch', ... }` to
  `{ kind: 'zarr-link', url }` for rows where a zarr/data link exists.
- Eventually retire the backend `POST .../neuroglancer` routes and the viewer
  registry. **No change to `NeuroglancerButton`'s appearance or to the table
  layout** — only the `source` value changes.

Per-row selection rule (future): prefer `zarr-link` when `zarr_path` is set;
fall back to `launch` for `.mrc`-only rows; `null` otherwise.

## Resolved decisions (2026-06-08)

1. **Dev `api` task** → change the default to `--no-reload` (step 4). Launches
   are first-class, so the default task must support them; hot-reload is lost in
   dev and noted in the README.
2. **Container/k8s NG port** → **fix the port and publish it** (steps 5 +
   §Deployment). zarr/Fileglancer stays the longer-term direction but is not
   required to ship this.
3. **Tilt-series button** → **fast-follow**, not in this plan's scope (Non-goals).
   The shared button already supports `entity: 'tilt-series'`.
4. **Memory ceiling** → **keep `NEUROGLANCER_MAX_VIEWERS=8`**; revisit only if
   the deployment host shows memory pressure.

## Open questions / risks

1. **`set_server_bind_address(bind_port=...)` support** in the pinned
   `neuroglancer >=2.40` — verify the kwarg exists before relying on a fixed
   port (env was not materializable during planning). This is a **hard
   prerequisite** for the publish step; tracked in step 5. If absent, find the
   equivalent fixed-port API the installed version exposes.
2. **TLS for the published Neuroglancer port** in k8s — the cluster router
   terminates TLS for nginx:80, but the directly-published NG port needs its own
   handling. Flag to ops during the k8s exposure work (step 5).
