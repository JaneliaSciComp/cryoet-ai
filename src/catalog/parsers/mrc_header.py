"""MRC header parser. Reads only the header (no voxel data)."""
from __future__ import annotations

from pathlib import Path

from catalog.parsers import ParseResult


def read_mrc_header(mrc_path: Path) -> ParseResult:
    """Read an MRC header and return image dimensions + voxel spacing.

    Fields:

    - ``image_size_x``: int  (from ``header.nx``)
    - ``image_size_y``: int  (from ``header.ny``)
    - ``image_size_z``: int  (from ``header.nz``)
    - ``voxel_spacing_angstrom``: float  (from ``voxel_size.x``, the
      canonical voxel spacing per Q6)

    ``status="missing"`` if ``mrc_path`` doesn't exist or isn't a regular
    file. ``status="unreadable"`` if ``mrcfile`` raises any exception.
    """
    if not mrc_path.is_file():
        return ParseResult(status="missing")
    try:
        import mrcfile

        with mrcfile.open(str(mrc_path), header_only=True, permissive=True) as m:
            h = m.header
            return ParseResult(
                fields={
                    "image_size_x": int(h.nx),
                    "image_size_y": int(h.ny),
                    "image_size_z": int(h.nz),
                    "voxel_spacing_angstrom": float(m.voxel_size.x),
                },
                status="ok",
            )
    except Exception as e:  # noqa: BLE001 - mrcfile raises a variety of types
        return ParseResult(status="unreadable", error=f"mrcfile error: {e}")
