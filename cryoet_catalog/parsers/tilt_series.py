"""Tilt-series parser.

Supports two on-disk MDOC layouts:

1. **Series-level** (rosenlab convention): one ``.mdoc`` per tilt-series
   with per-tilt ``[ZValue = N]`` sections inside. One MDOC → one
   ``TiltSeries`` record; ``tilt_angles`` come from the file's
   ``TiltAngle`` lines.

2. **Per-tilt** (gouauxlab convention): N ``.mdoc`` files per tilt-series
   (one per frame) with no ``[ZValue]`` sections. Filenames follow
   ``..._NNN_<angle>...`` so the angle is recoverable from the name. All
   MDOCs sharing a common prefix collapse to **one** ``TiltSeries`` record
   whose ``tilt_angles`` is the list of per-MDOC-extracted angles.

Mixed-layout directories are tolerated: each MDOC is classified
independently. Series-level MDOCs each become their own record; per-tilt
MDOCs are grouped by stripped prefix.

``microscope`` and ``camera`` are intentionally **not** populated from the
MDOC — those come from ``acquisition.toml`` (plan decision §11.14).

Stem collisions in the series-level branch are auto-disambiguated by
appending the parent-dir name (then a numeric suffix); each is reported as
a ``TiltSeriesCollision`` so the assembler can emit a
``tilt_series_id_collision`` scan warning (§11.23).

Layouts that match neither classifier (per-tilt MDOCs whose filenames lack
the ``_NNN_<angle>`` pattern with no series-level MDOC alongside) are
reported as ``layout_unknown`` so the assembler can emit a
``tilt_series_layout_unknown`` warning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from cryoet_schema import TiltSeries

from cryoet_catalog.parsers.mdoc import is_series_level_mdoc, parse_mdoc_file


# Tilt-image extensions used for ``image_format`` detection. ``.st`` and
# ``.mdoc`` are deliberately excluded — they're stack files / sidecars, not
# the raw tilt-image format the UI labels.
_FORMAT_EXTS: dict[str, Literal["EER", "TIFF", "MRC"]] = {
    ".eer": "EER",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".mrc": "MRC",
}

# Per-tilt filename grammar: prefix, then ``_NNN_<angle>``. ``NNN`` is a 3-
# to 5-digit acquisition index; ``<angle>`` is a signed decimal. Match runs
# on the full filename (e.g. ``foo_001_-20.0.eer.mdoc``) so we don't have
# to disambiguate ``.eer.mdoc`` vs ``.mdoc``.
_PER_TILT_FILENAME_RE = re.compile(
    r"^(?P<prefix>.+?)_\d{3,5}_(?P<angle>-?\d+(?:\.\d+)?)"
)


@dataclass
class TiltSeriesCollision:
    """One detected MDOC-stem collision (already auto-disambiguated)."""

    tilt_series_id: str  # the disambiguated id we ended up assigning
    original_stem: str  # the stem before disambiguation
    mdoc_path: str  # the MDOC whose stem collided


@dataclass
class TiltSeriesParseResult:
    records: list[TiltSeries] = field(default_factory=list)
    collisions: list[TiltSeriesCollision] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    layout_unknown: list[tuple[str, str]] = field(default_factory=list)


def _detect_image_format(
    frames_dir: Path,
) -> Literal["EER", "TIFF", "MRC"] | None:
    """Pick the unique tilt-image format present as direct children, or None.

    Returns None if no recognized formats are present OR if more than one
    format is present (ambiguous — the source dashboard makes the same call).
    """
    formats_seen: set[str] = set()
    for entry in frames_dir.iterdir():
        if not entry.is_file():
            continue
        fmt = _FORMAT_EXTS.get(entry.suffix.lower())
        if fmt is not None:
            formats_seen.add(fmt)
    if len(formats_seen) == 1:
        return formats_seen.pop()  # type: ignore[return-value]
    return None


def _find_zarr_for_stem(frames_dir: Path, stem: str) -> str | None:
    """Return ``<frames_dir>/<stem>.zarr`` if it exists as a directory."""
    candidate = frames_dir / f"{stem}.zarr"
    return str(candidate) if candidate.is_dir() else None


def _find_st_for_stem(frames_dir: Path, stem: str) -> str | None:
    """Return ``<frames_dir>/<stem>.st`` if it exists as a file."""
    candidate = frames_dir / f"{stem}.st"
    return str(candidate) if candidate.is_file() else None


def _per_tilt_group_key(filename: str) -> str | None:
    """Return the per-tilt group key for an MDOC filename, or ``None``.

    The group key is the filename prefix preceding ``_NNN_<angle>``. e.g.
    ``20241211_HippWaffle_49_001_-20.0.eer.mdoc`` → ``20241211_HippWaffle_49``.
    Returning ``None`` signals that the filename doesn't match the per-tilt
    pattern and should be reported as a layout-unknown MDOC.
    """
    m = _PER_TILT_FILENAME_RE.match(filename)
    return m.group("prefix") if m else None


def _extract_tilt_angle_from_filename(filename: str) -> float | None:
    """Pull the angle out of a per-tilt filename (``_NNN_<angle>...``)."""
    m = _PER_TILT_FILENAME_RE.match(filename)
    return float(m.group("angle")) if m else None


def _disambiguate_ids(
    mdoc_paths: list[Path],
) -> tuple[dict[Path, str], list[TiltSeriesCollision]]:
    """Map each MDOC path to a unique ``tilt_series_id``.

    Default id is ``mdoc_path.stem``. On collision, append the MDOC's
    parent-dir name (``<stem>__<parent>``); on still-colliding cases append
    a numeric suffix. Every disambiguated path is reported as a collision.
    """
    by_stem: dict[str, list[Path]] = {}
    for p in mdoc_paths:
        by_stem.setdefault(p.stem, []).append(p)

    ids: dict[Path, str] = {}
    collisions: list[TiltSeriesCollision] = []
    used: set[str] = set()

    for stem, paths in by_stem.items():
        if len(paths) == 1:
            ids[paths[0]] = stem
            used.add(stem)
            continue
        for p in paths:
            base = f"{stem}__{p.parent.name}"
            candidate = base
            n = 0
            while candidate in used:
                n += 1
                candidate = f"{base}_{n}"
            used.add(candidate)
            ids[p] = candidate
            collisions.append(
                TiltSeriesCollision(
                    tilt_series_id=candidate,
                    original_stem=stem,
                    mdoc_path=str(p),
                )
            )
    return ids, collisions


def _build_series_level_record(
    mdoc_path: Path,
    tilt_series_id: str,
    image_format: Literal["EER", "TIFF", "MRC"] | None,
) -> tuple[TiltSeries | None, tuple[str, str] | None]:
    """Build a record from a series-level MDOC; return ``(record, unreadable)``.

    On parse failure returns ``(None, (path, error))``; on missing-file
    (race) returns ``(None, None)``.
    """
    parsed = parse_mdoc_file(mdoc_path)
    if parsed.status == "unreadable":
        return None, (str(mdoc_path), parsed.error or "unreadable mdoc")
    if parsed.status == "missing":
        return None, None
    try:
        mtime: float | None = mdoc_path.stat().st_mtime
    except OSError:
        mtime = None

    f = parsed.fields
    angles = f.get("tilt_angles") or None  # collapse [] to None for storage
    return (
        TiltSeries(
            tilt_series_id=tilt_series_id,
            mdoc_path=str(mdoc_path),
            st_path=_find_st_for_stem(mdoc_path.parent, mdoc_path.stem),
            zarr_path=_find_zarr_for_stem(mdoc_path.parent, mdoc_path.stem),
            n_tilts=f.get("frame_count"),
            tilt_range_min=f.get("tilt_min"),
            tilt_range_max=f.get("tilt_max"),
            tilt_axis_angle=f.get("tilt_axis"),
            voltage=f.get("voltage"),
            pixel_spacing=f.get("pixel_size"),
            image_format=image_format,
            # microscope/camera from acquisition.toml only — left None here
            tilt_angles=angles,
            mtime=mtime,
        ),
        None,
    )


def _build_per_tilt_record(
    frames_dir: Path,
    tilt_series_id: str,
    mdocs: list[Path],
    image_format: Literal["EER", "TIFF", "MRC"] | None,
) -> tuple[TiltSeries, tuple[str, str] | None]:
    """Collapse a per-tilt MDOC group into one TiltSeries record.

    Returns ``(record, unreadable_or_None)`` — the unreadable entry is set
    when the *first* MDOC fails to content-parse (we still emit a record;
    angles come from filenames regardless).
    """
    sorted_mdocs = sorted(mdocs)
    angles = [
        a for p in sorted_mdocs
        if (a := _extract_tilt_angle_from_filename(p.name)) is not None
    ]

    # Pull header globals (Voltage / PixelSpacing / TiltAxisAngle) from the
    # first MDOC's content — per-tilt MDOCs still carry these in their
    # header even though they have no [ZValue] sections.
    voltage: float | None = None
    pixel_spacing: float | None = None
    tilt_axis: float | None = None
    unreadable: tuple[str, str] | None = None
    first = sorted_mdocs[0]
    parsed = parse_mdoc_file(first)
    if parsed.status == "unreadable":
        unreadable = (str(first), parsed.error or "unreadable mdoc")
    elif parsed.status == "ok":
        voltage = parsed.fields.get("voltage")
        pixel_spacing = parsed.fields.get("pixel_size")
        tilt_axis = parsed.fields.get("tilt_axis")

    mtimes: list[float] = []
    for p in sorted_mdocs:
        try:
            mtimes.append(p.stat().st_mtime)
        except OSError:
            pass
    mtime = max(mtimes) if mtimes else None

    return (
        TiltSeries(
            tilt_series_id=tilt_series_id,
            mdoc_path=str(first),
            st_path=_find_st_for_stem(frames_dir, tilt_series_id),
            zarr_path=_find_zarr_for_stem(frames_dir, tilt_series_id),
            n_tilts=len(angles) or None,
            tilt_range_min=min(angles) if angles else None,
            tilt_range_max=max(angles) if angles else None,
            tilt_axis_angle=tilt_axis,
            voltage=voltage,
            pixel_spacing=pixel_spacing,
            image_format=image_format,
            tilt_angles=angles or None,
            mtime=mtime,
        ),
        unreadable,
    )


def parse_tilt_series_dir(
    frames_dir: Path, acquisition_id: str | None = None
) -> TiltSeriesParseResult:
    """Walk MDOCs in ``frames_dir`` and emit ``TiltSeries`` records.

    Classifier branches per MDOC:

    - **Series-level**: contains ``[ZValue`` in its first 2 KB. One record
      per MDOC; ``tilt_angles`` from the file's ``TiltAngle`` lines.
    - **Per-tilt**: filename matches ``_NNN_<angle>``. Grouped by stripped
      prefix; each group collapses to one record whose ``tilt_angles`` is
      the list of per-MDOC angles.
    - **Unknown**: neither — reported via ``layout_unknown``.

    Empty result on missing dir or no MDOCs. Per-MDOC parse failures land
    in ``unreadable`` (records may still be emitted).
    """
    if not frames_dir.is_dir():
        return TiltSeriesParseResult()

    mdocs = sorted(frames_dir.glob("*.mdoc"))
    if not mdocs:
        return TiltSeriesParseResult()

    image_format = _detect_image_format(frames_dir)

    # Classify each MDOC. is_series_level_mdoc is the deciding signal —
    # presence of [ZValue means rosenlab-style series-level even if
    # multiple such MDOCs sit in the same dir.
    series_level: list[Path] = []
    per_tilt: list[Path] = []
    for p in mdocs:
        if is_series_level_mdoc(p):
            series_level.append(p)
        else:
            per_tilt.append(p)

    records: list[TiltSeries] = []
    collisions: list[TiltSeriesCollision] = []
    unreadable: list[tuple[str, str]] = []
    layout_unknown: list[tuple[str, str]] = []

    # --- Series-level branch ----------------------------------------------
    if series_level:
        id_map, sl_collisions = _disambiguate_ids(series_level)
        collisions.extend(sl_collisions)
        for mdoc_path in series_level:
            record, err = _build_series_level_record(
                mdoc_path, id_map[mdoc_path], image_format
            )
            if err is not None:
                unreadable.append(err)
            if record is not None:
                records.append(record)

    # --- Per-tilt branch --------------------------------------------------
    if per_tilt:
        groups: dict[str, list[Path]] = {}
        unmatched: list[Path] = []
        for p in per_tilt:
            key = _per_tilt_group_key(p.name)
            if key is None:
                unmatched.append(p)
            else:
                groups.setdefault(key, []).append(p)

        # Unmatched-filename warnings. If every per-tilt MDOC is unmatched
        # we report the whole dir as layout_unknown; otherwise the
        # un-grouped MDOCs surface as per-MDOC warnings (and their angles
        # are dropped from any nearby group).
        if unmatched and not groups:
            layout_unknown.append(
                (
                    str(frames_dir),
                    (
                        f"{len(unmatched)} non-series-level MDOC(s) in "
                        "frames dir match neither series-level "
                        "([ZValue) nor per-tilt (_NNN_<angle>) layouts"
                    ),
                )
            )
        else:
            for p in unmatched:
                layout_unknown.append(
                    (
                        str(p),
                        (
                            "per-tilt MDOC filename lacks _NNN_<angle> "
                            "pattern; angle dropped from collapsed "
                            "tilt_series.tilt_angles"
                        ),
                    )
                )

        for key, group_paths in groups.items():
            # On empty key (no prefix before _NNN_) fall back to
            # acquisition_id; absent that fall back to a literal sentinel.
            ts_id = key or acquisition_id or "tilt_series"
            record, err = _build_per_tilt_record(
                frames_dir, ts_id, group_paths, image_format
            )
            if err is not None:
                unreadable.append(err)
            records.append(record)

    return TiltSeriesParseResult(
        records=records,
        collisions=collisions,
        unreadable=unreadable,
        layout_unknown=layout_unknown,
    )


__all__ = [
    "TiltSeriesCollision",
    "TiltSeriesParseResult",
    "parse_tilt_series_dir",
]
