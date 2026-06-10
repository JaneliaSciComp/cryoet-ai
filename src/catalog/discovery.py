"""Pure path-walking discovery for the catalog scanner.

No file *contents* are read here — only directory entries and suffixes. Each
layer yields a frozen dataclass describing what was found on disk; the
orchestrator (scanner.py) drives the parsers from these locations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ANNOTATION_FILE_EXTENSIONS = frozenset(
    {".star", ".mrc", ".png", ".tiff", ".tif", ".csv", ".json"}
)
ZARR_DIR_SUFFIXES = (".zarr", ".ome.zarr")
REPRESENTATIVE_FRAME_SUFFIXES = frozenset({".eer", ".tiff", ".tif"})


@dataclass(frozen=True)
class SampleLocation:
    path: Path
    sample_id: str
    sample_toml: Path


@dataclass(frozen=True)
class AcquisitionLocation:
    path: Path
    sample_id: str
    acquisition_id: str
    acquisition_toml: Path | None
    frames_dir: Path | None
    tilt_series_dir: Path | None
    tomograms_dir: Path | None
    annotations_dir: Path | None


@dataclass(frozen=True)
class TomogramLocation:
    path: Path
    tomogram_id: str
    mrc_files: tuple[Path, ...]
    zarr_dirs: tuple[Path, ...]


@dataclass(frozen=True)
class AnnotationLocation:
    path: Path
    annotation_id: str
    files: tuple[Path, ...]


def _is_zarr_dir(path: Path) -> bool:
    name = path.name
    return any(name.endswith(suffix) for suffix in ZARR_DIR_SUFFIXES)


def dir_size_bytes(path: Path) -> int:
    """Total logical size (bytes) of everything under ``path``, recursively.

    Mirrors aicryoet-tools' approach: walk with os.scandir, sum st_size of
    regular files, do NOT follow symlinks, and silently skip directories we
    can't read (PermissionError / OSError on NFS). Counts all files on disk —
    frames, MDOCs, raw + post tomograms, OME-Zarr chunks, annotations, gain
    refs — not just cataloged ones.
    """
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += dir_size_bytes(Path(entry.path))
                except OSError:
                    continue  # entry vanished / unreadable mid-walk
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        pass
    return total


def iter_samples(root: Path) -> Iterator[SampleLocation]:
    """Yield SampleLocation for any direct child of ``root`` containing ``sample.toml``."""
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        sample_toml = child / "sample.toml"
        if sample_toml.is_file():
            yield SampleLocation(
                path=child,
                sample_id=child.name,
                sample_toml=sample_toml,
            )


def iter_acquisitions(sample: SampleLocation) -> Iterator[AcquisitionLocation]:
    """Yield AcquisitionLocation for any direct child of the sample dir that has
    either an ``acquisition.toml`` OR a ``Frames/`` subdirectory.
    """
    if not sample.path.is_dir():
        return
    for child in sorted(sample.path.iterdir()):
        if not child.is_dir():
            continue
        acq_toml = child / "acquisition.toml"
        frames = child / "Frames"
        has_toml = acq_toml.is_file()
        has_frames = frames.is_dir()
        if not (has_toml or has_frames):
            continue

        tilt_series = child / "TiltSeries"
        # Probe both layouts for the tomograms dir; v1 uses the same field
        # name for cryoet ("Reconstructions/Tomograms") and simulation
        # ("SyntheticCryoET").
        recon_tomos = child / "Reconstructions" / "Tomograms"
        synth_tomos = child / "SyntheticCryoET"
        if recon_tomos.is_dir():
            tomograms_dir: Path | None = recon_tomos
        elif synth_tomos.is_dir():
            tomograms_dir = synth_tomos
        else:
            tomograms_dir = None

        annotations = child / "Reconstructions" / "Annotations"

        yield AcquisitionLocation(
            path=child,
            sample_id=sample.sample_id,
            acquisition_id=child.name,
            acquisition_toml=acq_toml if has_toml else None,
            frames_dir=frames if has_frames else None,
            tilt_series_dir=tilt_series if tilt_series.is_dir() else None,
            tomograms_dir=tomograms_dir,
            annotations_dir=annotations if annotations.is_dir() else None,
        )


def iter_tomograms(acq: AcquisitionLocation) -> Iterator[TomogramLocation]:
    """Yield TomogramLocation for each direct child of ``acq.tomograms_dir``."""
    if acq.tomograms_dir is None or not acq.tomograms_dir.is_dir():
        return
    for child in sorted(acq.tomograms_dir.iterdir()):
        if not child.is_dir():
            continue
        mrc_files: list[Path] = []
        zarr_dirs: list[Path] = []
        for entry in sorted(child.iterdir()):
            if entry.is_file() and entry.suffix == ".mrc":
                mrc_files.append(entry)
            elif entry.is_dir() and _is_zarr_dir(entry):
                zarr_dirs.append(entry)
        yield TomogramLocation(
            path=child,
            tomogram_id=child.name,
            mrc_files=tuple(mrc_files),
            zarr_dirs=tuple(zarr_dirs),
        )


def iter_annotations(acq: AcquisitionLocation) -> Iterator[AnnotationLocation]:
    """Yield AnnotationLocation for each direct child of ``acq.annotations_dir``.

    Filters discovered file children by extension allowlist; treats ``.zarr`` /
    ``.ome.zarr`` directories as a single entry (not recursed).
    """
    if acq.annotations_dir is None or not acq.annotations_dir.is_dir():
        return
    for child in sorted(acq.annotations_dir.iterdir()):
        if not child.is_dir():
            continue
        kept: list[Path] = []
        for entry in child.iterdir():
            if entry.is_file():
                if entry.suffix.lower() in ANNOTATION_FILE_EXTENSIONS:
                    kept.append(entry)
            elif entry.is_dir() and _is_zarr_dir(entry):
                kept.append(entry)
        yield AnnotationLocation(
            path=child,
            annotation_id=child.name,
            files=tuple(sorted(kept, key=lambda p: str(p))),
        )


def parse_targets_for_sample(sample: SampleLocation) -> list[Path]:
    """Return every file the parsers will read for this sample.

    The orchestrator (scanner.py) consumes this to drive file-level mtime gating
    (§4.5). The list is deterministic, deduplicated, and sorted by string path.
    """
    targets: set[Path] = set()
    targets.add(sample.sample_toml)

    for acq in iter_acquisitions(sample):
        if acq.acquisition_toml is not None:
            targets.add(acq.acquisition_toml)

        if acq.frames_dir is not None and acq.frames_dir.is_dir():
            # MDOC files (direct children only).
            for mdoc in sorted(acq.frames_dir.glob("*.mdoc")):
                targets.add(mdoc)
            # Representative frame file: first by sorted name whose suffix
            # matches the camera-extension allowlist.
            for entry in sorted(acq.frames_dir.iterdir()):
                if entry.is_file() and entry.suffix.lower() in REPRESENTATIVE_FRAME_SUFFIXES:
                    targets.add(entry)
                    break

        for tomo in iter_tomograms(acq):
            for mrc in tomo.mrc_files:
                targets.add(mrc)
            for zarr_dir in tomo.zarr_dirs:
                zattrs = zarr_dir / ".zattrs"
                if zattrs.is_file():
                    targets.add(zattrs)

    return sorted(targets, key=lambda p: str(p))
