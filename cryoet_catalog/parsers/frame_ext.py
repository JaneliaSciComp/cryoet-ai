"""Camera inference from frame-file extensions inside a ``frames_dir``."""
from __future__ import annotations

from pathlib import Path

from cryoet_catalog.parsers import ParseResult


EXT_TO_CAMERA = {
    ".eer": "Falcon",
    ".tiff": "K3",
    ".tif": "K3",
}


def infer_camera(frames_dir: Path) -> ParseResult:
    """Infer the camera by looking at frame-file extensions in ``frames_dir``.

    ``status="missing"`` if ``frames_dir`` doesn't exist or contains no
    recognized frame files.

    ``status="unreadable"`` (category: ``ambiguous_frame_extension``) if
    BOTH ``.eer`` AND ``.tiff``/``.tif`` are present — the assembler treats
    this as a conflict.

    ``status="ok"`` with ``fields={"camera": "Falcon"|"K3"}`` otherwise.
    """
    if not frames_dir.is_dir():
        return ParseResult(status="missing")
    exts_seen: set[str] = set()
    for child in frames_dir.iterdir():
        if not child.is_file():
            continue
        suffix = child.suffix.lower()
        if suffix in EXT_TO_CAMERA:
            exts_seen.add(suffix)
    if not exts_seen:
        return ParseResult(status="missing")
    cameras = {EXT_TO_CAMERA[e] for e in exts_seen}
    if len(cameras) > 1:
        return ParseResult(
            status="unreadable",
            error=f"ambiguous frame extensions: {sorted(exts_seen)}",
        )
    return ParseResult(fields={"camera": cameras.pop()}, status="ok")
