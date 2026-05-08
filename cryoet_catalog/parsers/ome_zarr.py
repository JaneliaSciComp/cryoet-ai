"""OME-Zarr ``.zattrs`` reader.

We only need axis names and the pixel scale of the first dataset; we do
NOT open the array itself. A plain ``json.loads`` on ``.zattrs`` is
sufficient and avoids a hard dependency on the ``zarr`` package.
"""
from __future__ import annotations

import json
from pathlib import Path

from cryoet_catalog.parsers import ParseResult


def read_zarr_attrs(zarr_path: Path) -> ParseResult:
    """Read ``<zarr_path>/.zattrs`` and extract OME-NGFF axis/scale.

    Fields:

    - ``zarr_axes``: str  (joined axis names, e.g. ``"zyx"``)
    - ``zarr_scale``: list[float]  (first dataset's first scale transformation)

    ``status="missing"`` if ``zarr_path`` doesn't exist or has no
    ``.zattrs``. ``status="unreadable"`` if ``.zattrs`` is malformed JSON
    or missing the expected ``multiscales[0].axes`` /
    ``datasets[0].coordinateTransformations`` shape.
    """
    if not zarr_path.exists():
        return ParseResult(status="missing")
    zattrs = zarr_path / ".zattrs"
    if not zattrs.is_file():
        return ParseResult(status="missing")
    try:
        data = json.loads(zattrs.read_text())
    except Exception as e:  # noqa: BLE001
        return ParseResult(
            status="unreadable", error=f"zarr .zattrs not valid JSON: {e}"
        )
    try:
        ms = data["multiscales"][0]
        axes = ms["axes"]
        zarr_axes = "".join(a["name"] for a in axes)
        ds = ms["datasets"][0]
        scale = next(
            t["scale"]
            for t in ds["coordinateTransformations"]
            if t["type"] == "scale"
        )
        zarr_scale = [float(x) for x in scale]
    except (KeyError, IndexError, StopIteration, TypeError) as e:
        return ParseResult(
            status="unreadable",
            error=f"zarr .zattrs missing expected keys: {e}",
        )
    return ParseResult(
        fields={"zarr_axes": zarr_axes, "zarr_scale": zarr_scale},
        status="ok",
    )
