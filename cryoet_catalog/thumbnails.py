"""Pre-generate tomogram center-slice thumbnails into a filesystem cache."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

THUMBNAIL_WIDTH = 512


@dataclass(frozen=True)
class TomoRef:
    acquisition_id: str
    kind: str  # "post" or "raw"
    tomogram_id: str
    mrc_path: str | None


def _safe_segment(value: str) -> str:
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        raise ValueError(f"unsafe id segment: {value!r}")
    return value


def _relpath(sample_id: str, acquisition_id: str, tomogram_id: str) -> str:
    return "/".join((
        _safe_segment(sample_id),
        _safe_segment(acquisition_id),
        _safe_segment(tomogram_id) + ".png",
    ))


def _render_one(mrc_path: str, dest: Path) -> bool:
    from cryoet_catalog.imaging._mrc import render_center_xy_slice_png

    try:
        png = render_center_xy_slice_png(mrc_path, width=THUMBNAIL_WIDTH)
    except Exception as e:
        logger.warning("thumbnail render failed for %s: %s", mrc_path, e)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".png.tmp")
    tmp.write_bytes(png)
    tmp.replace(dest)
    return True


def generate_thumbnails(
    sample_id: str,
    tomos: list[TomoRef],
    thumbnail_root: Path,
    *,
    skip_existing: bool = False,
) -> str | None:
    generated: dict[tuple[str, str], str] = {}
    for ref in sorted(tomos, key=lambda r: (r.acquisition_id, r.kind != "post", r.tomogram_id)):
        if not ref.mrc_path:
            continue
        rel = _relpath(sample_id, ref.acquisition_id, ref.tomogram_id)
        dest = thumbnail_root / rel
        ok = True if (skip_existing and dest.is_file()) else _render_one(ref.mrc_path, dest)
        if ok:
            generated.setdefault((ref.acquisition_id, ref.kind), rel)

    return representative_relpath(generated)


def representative_relpath(generated: dict[tuple[str, str], str]) -> str | None:
    for acq_id in sorted({a for a, _ in generated}):
        rel = generated.get((acq_id, "post")) or generated.get((acq_id, "raw"))
        if rel:
            return rel
    return None


def refs_from_record(record) -> list[TomoRef]:
    refs: list[TomoRef] = []
    for acq_id, acq in record.acquisitions.items():
        for t in acq.post_processed_tomogram:
            refs.append(TomoRef(acq_id, "post", t.tomogram_id, t.mrc_path))
        if acq.raw_tomogram is not None:
            r = acq.raw_tomogram
            refs.append(TomoRef(acq_id, "raw", r.tomogram_id, r.mrc_path))
    return refs


def refs_from_db(session, sample_id: str) -> list[TomoRef]:
    from cryoet_catalog import orm
    from sqlalchemy import select

    refs: list[TomoRef] = []
    for r in session.execute(
        select(orm.PostProcessedTomogramORM).where(
            orm.PostProcessedTomogramORM.sample_id == sample_id)
    ).scalars():
        refs.append(TomoRef(r.acquisition_id, "post", r.tomogram_id, r.mrc_path))
    for r in session.execute(
        select(orm.RawTomogramORM).where(
            orm.RawTomogramORM.sample_id == sample_id)
    ).scalars():
        refs.append(TomoRef(r.acquisition_id, "raw", r.tomogram_id, r.mrc_path))
    return refs
