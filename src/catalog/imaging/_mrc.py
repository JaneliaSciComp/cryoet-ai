"""MRC tomogram slice rendering for the preview endpoint.

Originally vendored from
``aicryoet-tools/src/aicryoet_tools/tomogram.py`` and
``aicryoet-tools/src/aicryoet_tools/web_utils.py`` at commit ``083ccec``.

This module exposes ``render_center_xy_slice_png(mrc_path)`` which returns
raw PNG bytes — never a data URI — so the FastAPI route can stream the
image with the right ``Content-Type`` and ETag headers (the dashboard
parent used base64 data URIs which we don't want over HTTP).

No matplotlib ``pyplot`` use — figures are built via the OO API
(``Figure() + FigureCanvasAgg``) so concurrent renders on the threadpool
don't share global state (plan §7.5 / §11.6).
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Literal

import mrcfile
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


def _axis_index(mapc: int, mapr: int, maps: int, axis: Literal["x", "y", "z"]) -> int:
    """Return the numpy-array index for a physical axis given MRC mapc/mapr/maps."""
    axis_num = {"x": 1, "y": 2, "z": 3}[axis]
    if maps == axis_num:
        return 0
    if mapr == axis_num:
        return 1
    if mapc == axis_num:
        return 2
    raise ValueError(f"axis {axis!r} not present in MRC axis mapping")


def _center_xy_slice(mrc_path: Path) -> np.ndarray:
    """Read an MRC and return the center XY slice as a 2D float32 array.

    Uses the header's ``mapc/mapr/maps`` axis mapping (1=X, 2=Y, 3=Z) so the
    returned slice is the physical-XY plane regardless of the underlying
    storage order — matching ``Tomogram.center_xy_slice`` in the vendored
    source.
    """
    with mrcfile.open(str(mrc_path), mode="r", permissive=True) as mrc:
        mapc = int(mrc.header.mapc)
        mapr = int(mrc.header.mapr)
        maps = int(mrc.header.maps)
        z_idx = _axis_index(mapc, mapr, maps, "z")
        z_center = mrc.data.shape[z_idx] // 2
        slice_2d = np.take(mrc.data, z_center, axis=z_idx)
    return np.asarray(slice_2d, dtype=np.float32)


def _array_to_png_bytes(
    arr: np.ndarray,
    *,
    percentile: tuple[float, float] = (1, 99),
    width: int = 1200,
    cmap: str = "gray",
) -> bytes:
    """Render a 2D array as a PNG with percentile contrast clipping.

    Uses the matplotlib OO API (``Figure() + FigureCanvasAgg``); no
    ``pyplot`` global state so concurrent renders on the threadpool are
    safe.
    """
    vmin, vmax = np.percentile(arr, percentile)
    aspect = arr.shape[0] / arr.shape[1] if arr.shape[1] else 1.0
    dpi = 100
    fig_w = width / dpi
    fig_h = fig_w * aspect

    fig = Figure(figsize=(fig_w, fig_h), dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    buf = BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()


def render_center_xy_slice_png(mrc_path: Path | str, *, width: int = 1200) -> bytes:
    """Render the center XY slice of an MRC volume as PNG bytes.

    :param mrc_path: Path to the MRC file. Should already be path-validated
        against ``CATALOG_DATA_ROOT`` by the caller (route handler).
    :param width: Output image width in pixels.
    :return: PNG image bytes.
    """
    slice_2d = _center_xy_slice(Path(mrc_path))
    return _array_to_png_bytes(slice_2d, percentile=(1, 99), width=width)


def read_mrc_volume(mrc_path: Path | str) -> tuple[np.ndarray, tuple[float, float, float], str]:
    """Load the full MRC volume + voxel size + axis order for Neuroglancer.

    Returns ``(data, voxel_size_in_array_order, axis_order_string)``.
    Voxel size is reordered to match the array axes (slowest → fastest), so
    callers can feed it directly into ``view_neuroglancer``.
    """
    mrc_path = Path(mrc_path)
    with mrcfile.open(str(mrc_path), mode="r", permissive=True) as mrc:
        data = mrc.data.copy()
        vx = float(mrc.voxel_size.x)
        vy = float(mrc.voxel_size.y)
        vz = float(mrc.voxel_size.z)
        mapc = int(mrc.header.mapc)
        mapr = int(mrc.header.mapr)
        maps = int(mrc.header.maps)
    axis_names = {1: "x", 2: "y", 3: "z"}
    axis_order = f"{axis_names[maps]}{axis_names[mapr]}{axis_names[mapc]}"
    voxel_map = {"x": vx, "y": vy, "z": vz}
    voxel_size = (voxel_map[axis_order[0]], voxel_map[axis_order[1]], voxel_map[axis_order[2]])
    return data, voxel_size, axis_order
