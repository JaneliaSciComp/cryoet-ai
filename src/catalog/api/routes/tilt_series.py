"""Tilt-series preview + polar + Neuroglancer endpoints (plan §7.5).

Composite-key URLs throughout: ``/tilt-series/{sample_id}/{acquisition_id}/
{tilt_series_id}/...`` (decision §11.8).

Preview path order: prefer ``zarr_path`` (lazy, fast); fall back to TIFF/MRC
siblings in the frames directory (skipping EER for the preview — too slow
to sum at request time). The polar plot uses cached ``tilt_angles`` from
the DB row — no MDOC re-parsing.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from catalog import orm
from catalog.api.deps import get_session
from catalog.api.path_validation import validate_under_data_root
from catalog.api.routes.tomograms import launch_viewer_in_registry
from catalog.api.schemas import ViewerLaunchOut

router = APIRouter()


def _lookup_tilt_series(
    session: Session, sample_id: str, acquisition_id: str, tilt_series_id: str
) -> orm.TiltSeriesORM:
    sample = session.get(orm.SampleORM, sample_id)
    if sample is None or sample.deleted_at is not None:
        raise HTTPException(status_code=404, detail="sample not found")
    row = session.get(
        orm.TiltSeriesORM, (sample_id, acquisition_id, tilt_series_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="tilt series not found")
    return row


# ── Preview ───────────────────────────────────────────────────────────────


def _render_zarr_median_png(zarr_path: str) -> bytes:
    """Read median-tilt from a zarr store and render to PNG bytes."""
    import numpy as np
    import zarr

    from catalog.imaging._mrc import _array_to_png_bytes

    root = zarr.open_group(zarr_path, mode="r")
    ds = root["tilt_series"]
    tilt_angles = list(root.attrs.get("tilt_angles", []))
    if tilt_angles:
        median_angle = float(np.median(tilt_angles))
        median_idx = min(
            range(len(tilt_angles)),
            key=lambda i: abs(tilt_angles[i] - median_angle),
        )
    else:
        median_idx = ds.shape[0] // 2
    img = np.array(ds[median_idx], dtype=np.float32)
    return _array_to_png_bytes(img, percentile=(5, 95), width=800)


def _render_frames_median_png(frames_dir: str) -> bytes:
    """Find the median-angle TIFF/MRC tilt in ``frames_dir`` and render it."""
    import numpy as np

    from catalog.imaging._mrc import _array_to_png_bytes
    from catalog.imaging._tilt_image import (
        find_viewable_tilt_images,
        load_tilt_image,
    )

    tilt_images = find_viewable_tilt_images(Path(frames_dir))
    if not tilt_images:
        raise FileNotFoundError("no viewable tilt images")
    angles = [a for a, _ in tilt_images]
    median_angle = float(np.median(angles))
    _, center_path = min(tilt_images, key=lambda x: abs(x[0] - median_angle))
    img = load_tilt_image(center_path, gain=None, preview=True)
    return _array_to_png_bytes(img.astype(np.float32), percentile=(5, 95), width=800)


@router.get(
    "/{sample_id}/{acquisition_id}/{tilt_series_id}/preview.png"
)
async def tilt_series_preview(
    sample_id: str,
    acquisition_id: str,
    tilt_series_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Median-angle tilt image as PNG. Prefer zarr; fall back to TIFF/MRC.

    422 if neither a zarr store nor viewable frames exist.
    """
    row = _lookup_tilt_series(session, sample_id, acquisition_id, tilt_series_id)

    if row.zarr_path:
        resolved = validate_under_data_root(request, row.zarr_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="zarr path missing on disk")
        png_bytes = await run_in_threadpool(_render_zarr_median_png, str(resolved))
    else:
        if not row.mdoc_path:
            raise HTTPException(status_code=422, detail="no mdoc_path or zarr_path")
        mdoc_resolved = validate_under_data_root(request, row.mdoc_path)
        frames_dir = mdoc_resolved.parent if mdoc_resolved.is_file() else mdoc_resolved
        if not frames_dir.is_dir():
            raise HTTPException(status_code=422, detail="frames dir not found")
        try:
            png_bytes = await run_in_threadpool(
                _render_frames_median_png, str(frames_dir)
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Polar plot ────────────────────────────────────────────────────────────


@lru_cache(maxsize=128)
def _cached_polar_png(
    sample_id: str,
    acquisition_id: str,
    tilt_series_id: str,
    mtime: float | None,
    version: int,
    angles_tuple: tuple[float, ...],
) -> bytes:
    """LRU-cache the polar render keyed on the plan's cache key.

    ``angles_tuple`` is in the key so changes to the cached angles list
    invalidate even if mtime is unavailable (e.g. mdoc deleted post-scan).
    """
    from catalog.imaging._polar import render_polar_png

    return render_polar_png(list(angles_tuple))


@router.get(
    "/{sample_id}/{acquisition_id}/{tilt_series_id}/polar.png"
)
async def tilt_series_polar(
    sample_id: str,
    acquisition_id: str,
    tilt_series_id: str,
    session: Session = Depends(get_session),
):
    """Semicircular polar plot of cached ``tilt_angles``.

    422 if the row has no cached angles. Does NOT re-parse the MDOC.
    """
    from catalog.imaging._polar import POLAR_RENDER_VERSION

    row = _lookup_tilt_series(session, sample_id, acquisition_id, tilt_series_id)
    angles = row.tilt_angles or []
    if not angles:
        raise HTTPException(status_code=422, detail="no cached tilt angles")

    png_bytes = await run_in_threadpool(
        _cached_polar_png,
        sample_id,
        acquisition_id,
        tilt_series_id,
        row.mtime,
        POLAR_RENDER_VERSION,
        tuple(float(a) for a in angles),
    )
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Neuroglancer ──────────────────────────────────────────────────────────


def _load_zarr_stack(zarr_path: str):
    """Load the full zarr tilt stack + median index + pixel spacing tuple."""
    import numpy as np
    import zarr

    root = zarr.open_group(zarr_path, mode="r")
    ds = root["tilt_series"]
    tilt_angles = list(root.attrs.get("tilt_angles", list(range(ds.shape[0]))))
    median_angle = float(np.median(tilt_angles))
    median_idx = min(
        range(len(tilt_angles)),
        key=lambda i: abs(tilt_angles[i] - median_angle),
    )
    stack = np.array(ds[:], dtype=np.float32)
    return stack, median_idx, tilt_angles


def _load_frames_stack(frames_dir: str):
    """Load TIFF/MRC tilt frames as a 3D stack."""
    import numpy as np

    from catalog.imaging._tilt_image import (
        find_viewable_tilt_images,
        load_tilt_image,
    )

    tilt_images = find_viewable_tilt_images(Path(frames_dir))
    if not tilt_images:
        raise FileNotFoundError("no viewable tilt images")
    angles = [a for a, _ in tilt_images]
    median_angle = float(np.median(angles))
    median_idx = min(range(len(angles)), key=lambda i: abs(angles[i] - median_angle))
    stack = np.stack(
        [load_tilt_image(p, gain=None, preview=True).astype(np.float32) for _, p in tilt_images]
    )
    return stack, median_idx, angles


@router.post(
    "/{sample_id}/{acquisition_id}/{tilt_series_id}/neuroglancer",
    response_model=ViewerLaunchOut,
)
async def tilt_series_neuroglancer(
    sample_id: str,
    acquisition_id: str,
    tilt_series_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Launch a Neuroglancer viewer over the tilt-series stack.

    Prefer zarr (lazy, fast); fall back to TIFF/MRC frames. 422 if neither
    is reachable.
    """
    row = _lookup_tilt_series(session, sample_id, acquisition_id, tilt_series_id)
    pixel_spacing = float(row.pixel_spacing) if row.pixel_spacing else 1.0

    if row.zarr_path:
        resolved = validate_under_data_root(request, row.zarr_path)
        if not resolved.exists():
            raise HTTPException(status_code=422, detail="zarr path missing on disk")
        source = ("zarr", str(resolved))
    else:
        if not row.mdoc_path:
            raise HTTPException(status_code=422, detail="no mdoc_path or zarr_path")
        mdoc_resolved = validate_under_data_root(request, row.mdoc_path)
        frames_dir = mdoc_resolved.parent if mdoc_resolved.is_file() else mdoc_resolved
        if not frames_dir.is_dir():
            raise HTTPException(status_code=422, detail="frames dir not found")
        source = ("frames", str(frames_dir))

    layer_name = Path(row.zarr_path or row.mdoc_path).stem

    def launch():
        from catalog.imaging._neuroglancer import view_neuroglancer

        kind, path = source
        if kind == "zarr":
            stack, median_idx, _angles = _load_zarr_stack(path)
        else:
            stack, median_idx, _angles = _load_frames_stack(path)
        return view_neuroglancer(
            stack,
            name=layer_name,
            voxel_size=(1.0, pixel_spacing, pixel_spacing),
            axis_names=("z", "y", "x"),
            layout="xy",
            contrast_percentile=(5, 95),
            initial_position=(median_idx, stack.shape[1] // 2, stack.shape[2] // 2),
        )

    url = await launch_viewer_in_registry(
        request, ("tilt_series", sample_id, acquisition_id, tilt_series_id), launch
    )
    return ViewerLaunchOut(url=url)
