"""GET /thumbnails/{relpath:path} — stream a pre-generated PNG from the cache."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()


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
