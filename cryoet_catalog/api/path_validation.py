"""Path validation against ``CATALOG_DATA_ROOT``.

Used by every preview / Neuroglancer route to refuse paths that resolve
outside the configured data root (decision §11.16 of the dashboard MVP plan).
Defense in depth for the API/scanner-different-host case (HHMI norm) and
against symlink-traversal escapes from absolute paths recorded in the DB.

Caveats:
- TOCTOU between ``Path.resolve(strict=True)`` and the actual file open is
  acceptable on a trusted network.
- Zarr internal symlinks (chunks pointing outside the resolved Zarr dir)
  are not blocked — Zarr stores must not contain external symlinks.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request


def validate_under_data_root(request: Request, candidate: str | Path) -> Path:
    """Resolve ``candidate`` and confirm it sits under ``data_root_resolved``.

    Raises ``HTTPException(404)`` if the path is missing, unresolvable, or
    escapes the data root (after symlink resolution). Returns the resolved
    absolute path on success.
    """
    data_root = getattr(request.app.state, "data_root_resolved", None)
    if data_root is None:
        raise HTTPException(status_code=500, detail="data root not configured")
    try:
        resolved = Path(candidate).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail="path not found")
    if not resolved.is_relative_to(data_root):
        raise HTTPException(status_code=404, detail="path outside data root")
    return resolved
