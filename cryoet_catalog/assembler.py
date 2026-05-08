"""Assembler: merges parser outputs for one sample into a validated SampleRecord.

Inputs: a SampleLocation. Outputs: AssemblyResult with the merged record, the
list of structured warnings (per Q7), any cross-source conflicts, the structured
extras list (passed through from cryoet_schema.loader for persistence), and a
tomogram_aux side-channel for DB-only values (voxel_spacing_angstrom from MRC
header, voxel_spacing_angstrom_implied from pixel_size x voxel_bin).

The assembler is the sole creator of ScanWarning objects; persistence is a
dumb writer that stamps detected_at and scan_run_id at insert time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from cryoet_schema import Acquisition, AcquisitionFile, SampleRecord
from cryoet_schema.loader import ExtrasEntry

from cryoet_catalog.discovery import (
    SampleLocation,
    iter_acquisitions,
    iter_annotations,
    iter_tomograms,
)
from cryoet_catalog.parsers.frame_ext import infer_camera
from cryoet_catalog.parsers.mdoc import parse_acquisition_mdocs
from cryoet_catalog.parsers.mrc_header import read_mrc_header
from cryoet_catalog.parsers.ome_zarr import read_zarr_attrs
from cryoet_catalog.parsers.toml_files import load_sample_toml


ScanWarningCategory = Literal[
    "extra_field",
    "possible_typo",
    "unfilled_placeholder",
    "missing_acquisition_toml",
    "unparseable_acquisition_toml",
    "unparseable_mdoc",
    "unparseable_mrc_header",
    "unparseable_zarr_attrs",
    "ambiguous_frame_extension",
    "voxel_spacing_implied_mismatch",
]


@dataclass
class ScanWarning:
    category: str
    location: str
    message: str


@dataclass
class FieldConflict:
    location: str
    category: str
    values: dict[str, Any]
    severity: str = "warning"  # "warning" | "error"


@dataclass
class AssemblyResult:
    record: SampleRecord | None
    warnings: list[ScanWarning] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)
    extras: list[ExtrasEntry] = field(default_factory=list)
    tomogram_aux: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )


_TYPO_LOC_RE = re.compile(r"on (\w+) closely matches")
_EXTRA_AT_RE = re.compile(r"extra field '[^']+' at '([^']+)' \(not in schema\)")


def _categorize_loader_warning(s: str) -> ScanWarning:
    """Convert a loader warning string into a structured ScanWarning.

    The loader's warning strings have stable prefixes (verified in
    ``cryoet_schema/loader.py``):

    - ``"extra field 'X' on <Model> closely matches known field 'Y' (similarity N); possible typo"``
      -> category ``possible_typo``; location is the model name (or
      ``"<root>"`` if not parseable).
    - ``"extra field 'X' at 'LOC' (not in schema)"``
      -> category ``extra_field``; location parsed out of the message.
    - ``"<dotted.path>: unfilled <FILL IN> placeholder"``
      -> category ``unfilled_placeholder``; location is the dotted path.

    Anything else falls through to ``extra_field`` with ``<unknown>`` location.
    """
    if "possible typo" in s:
        m = _TYPO_LOC_RE.search(s)
        location = m.group(1) if m else "<root>"
        return ScanWarning(category="possible_typo", location=location, message=s)
    if "not in schema" in s:
        m = _EXTRA_AT_RE.search(s)
        location = m.group(1) if m else "<unknown>"
        return ScanWarning(category="extra_field", location=location, message=s)
    if "unfilled <FILL IN> placeholder" in s:
        # Format: "<path>: unfilled <FILL IN> placeholder"
        head, sep, _ = s.partition(": unfilled <FILL IN> placeholder")
        location = head if sep else "<unknown>"
        return ScanWarning(
            category="unfilled_placeholder", location=location, message=s
        )
    return ScanWarning(category="extra_field", location="<unknown>", message=s)


def _relative_close(a: float, b: float, rel_tol: float = 1e-3) -> bool:
    """Relative tolerance comparison: |a-b| / max(|a|, |b|, 1) < rel_tol."""
    return abs(a - b) / max(abs(a), abs(b), 1.0) < rel_tol


def assemble_sample(
    sample_loc: SampleLocation,
    *,
    on_voxel_mismatch: Literal["warn", "error"] = "warn",
) -> AssemblyResult:
    """Assemble one sample's discovery + parser outputs into a SampleRecord.

    Implements §4.6 merge rules 1-7:

    1. Load TOML via the schema loader; bail out (record=None) if the sample
       block is unrecoverable.
    1.5. Synthesize empty AcquisitionFile entries for filesystem acquisitions
       that aren't in record.acquisitions (Frames-only or unparseable
       acquisition.toml). Emit categorized warnings.
    2. Per-acquisition: run MDOC + frame-extension parsers; fill in fields
       on the Acquisition Pydantic model that are still None.
    3. Per-tomogram: run MRC header + OME-Zarr parsers; fill image_size_*,
       mrc_path, zarr_path, zarr_axes/scale on the Tomogram model. MRC
       voxel_spacing_angstrom goes to ``tomogram_aux`` (DB-only).
    4. Cryoet-only voxel-spacing consistency check using a relative tolerance
       (1e-3). Stores the implied value (pixel_size * voxel_bin) in
       ``tomogram_aux``; on mismatch records a FieldConflict and emits a
       warning (or appends to ``errors`` when ``on_voxel_mismatch='error'``).
    5. Derived fields: per-tomogram ``is_raw = (derived_from == [])``.
       Chromatin ``linker_length_fraction`` derivation is a no-op for v1
       (the source field doesn't exist on the Chromatin model).
    6. Per-annotation: assign sorted file paths from disk discovery onto
       ``Annotation.files``.
    7. Re-validate the populated record via
       ``SampleRecord.model_validate(record.model_dump(by_alias=True))`` to
       catch anything we just violated. On failure, errors are recorded and
       record is set back to None.
    """
    result = AssemblyResult(record=None)

    # ── Step 1: TOML ─────────────────────────────────────────────────────────
    load = load_sample_toml(sample_loc.path)

    for w in load.warnings:
        result.warnings.append(_categorize_loader_warning(w))
    result.extras = list(load.extras)

    if load.sample_errors:
        result.errors.extend(load.sample_errors)
        return result
    if load.record is None:
        result.errors.append("loader returned no record and no sample_errors")
        return result

    record = load.record
    sample_id = sample_loc.sample_id

    # ── Step 1.5: synthesize missing/unparseable acquisitions ────────────────
    fs_acquisitions = list(iter_acquisitions(sample_loc))
    record_acq_ids = set(record.acquisitions.keys())

    new_acquisitions = dict(record.acquisitions)
    for acq_loc in fs_acquisitions:
        if acq_loc.acquisition_id in record_acq_ids:
            continue
        if acq_loc.acquisition_id in load.acquisition_errors:
            category = "unparseable_acquisition_toml"
            message = load.acquisition_errors[acq_loc.acquisition_id]
        else:
            category = "missing_acquisition_toml"
            message = f"no acquisition.toml at {acq_loc.path}/acquisition.toml"
        result.warnings.append(
            ScanWarning(
                category=category,
                location=f"acquisitions.{acq_loc.acquisition_id}",
                message=message,
            )
        )
        synth = AcquisitionFile(
            acquisition=Acquisition(acquisition_id=acq_loc.acquisition_id),
            tomogram=[],
            annotation=[],
        )
        new_acquisitions[acq_loc.acquisition_id] = synth

    record = record.model_copy(update={"acquisitions": new_acquisitions})

    # ── Steps 2, 3, 4, 5, 6: walk each acquisition ───────────────────────────
    MDOC_FIELDS = (
        "pixel_size",
        "voltage",
        "energy_filter_slit_width",
        "date_collected",
        "frame_count",
        "dose_per_tilt",
        "total_dose",
        "tilt_min",
        "tilt_max",
        "tilt_axis",
        "defocus_per_image",
    )

    for acq_loc in fs_acquisitions:
        acq_file = record.acquisitions[acq_loc.acquisition_id]
        acq = acq_file.acquisition

        # Step 2: MDOC + frame-ext ------------------------------------------
        if acq_loc.frames_dir is not None:
            mdoc_result = parse_acquisition_mdocs(acq_loc.frames_dir)
            if mdoc_result.status == "unreadable":
                result.warnings.append(
                    ScanWarning(
                        category="unparseable_mdoc",
                        location=f"acquisitions.{acq_loc.acquisition_id}.Frames",
                        message=mdoc_result.error or "unparseable mdoc",
                    )
                )
            elif mdoc_result.status == "ok":
                for fname in MDOC_FIELDS:
                    if fname in mdoc_result.fields and getattr(acq, fname, None) is None:
                        setattr(acq, fname, mdoc_result.fields[fname])

            cam_result = infer_camera(acq_loc.frames_dir)
            if cam_result.status == "unreadable":
                result.warnings.append(
                    ScanWarning(
                        category="ambiguous_frame_extension",
                        location=f"acquisitions.{acq_loc.acquisition_id}.Frames",
                        message=cam_result.error or "ambiguous frame extension",
                    )
                )
            elif cam_result.status == "ok" and acq.camera is None:
                acq.camera = cam_result.fields.get("camera")

        # Step 3 + 4: tomograms ---------------------------------------------
        existing_tomos = {t.tomogram_id: t for t in acq_file.tomogram}
        for tomo_loc in iter_tomograms(acq_loc):
            tomo = existing_tomos.get(tomo_loc.tomogram_id)
            if tomo is None:
                # Tomogram folder on disk not declared in acquisition.toml.
                # v1 does not synthesize tomograms; warn so a forgotten
                # [[tomogram]] block doesn't go unnoticed.
                result.warnings.append(
                    ScanWarning(
                        category="undeclared_tomogram_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tomogram[{tomo_loc.tomogram_id}]"
                        ),
                        message=(
                            f"folder '{tomo_loc.tomogram_id}' exists on disk but is "
                            "not declared in acquisition.toml — add a [[tomogram]] "
                            f"block with id = \"{tomo_loc.tomogram_id}\""
                        ),
                    )
                )
                continue

            mrc_voxel_spacing: float | None = None
            mrc_path_str: str | None = None
            if tomo_loc.mrc_files:
                mrc_path_str = str(tomo_loc.mrc_files[0])
                mrc_result = read_mrc_header(tomo_loc.mrc_files[0])
                if mrc_result.status == "unreadable":
                    result.warnings.append(
                        ScanWarning(
                            category="unparseable_mrc_header",
                            location=(
                                f"acquisitions.{acq_loc.acquisition_id}"
                                f".tomogram[{tomo_loc.tomogram_id}]"
                            ),
                            message=mrc_result.error or "unparseable mrc",
                        )
                    )
                elif mrc_result.status == "ok":
                    if tomo.image_size_x is None:
                        tomo.image_size_x = mrc_result.fields.get("image_size_x")
                    if tomo.image_size_y is None:
                        tomo.image_size_y = mrc_result.fields.get("image_size_y")
                    if tomo.image_size_z is None:
                        tomo.image_size_z = mrc_result.fields.get("image_size_z")
                    mrc_voxel_spacing = mrc_result.fields.get("voxel_spacing_angstrom")
            if tomo.mrc_path is None and mrc_path_str:
                tomo.mrc_path = mrc_path_str

            zarr_path_str: str | None = None
            if tomo_loc.zarr_dirs:
                zarr_path_str = str(tomo_loc.zarr_dirs[0])
                zarr_result = read_zarr_attrs(tomo_loc.zarr_dirs[0])
                if zarr_result.status == "unreadable":
                    result.warnings.append(
                        ScanWarning(
                            category="unparseable_zarr_attrs",
                            location=(
                                f"acquisitions.{acq_loc.acquisition_id}"
                                f".tomogram[{tomo_loc.tomogram_id}]"
                            ),
                            message=zarr_result.error or "unparseable zarr",
                        )
                    )
                elif zarr_result.status == "ok":
                    if tomo.zarr_axes is None:
                        tomo.zarr_axes = zarr_result.fields.get("zarr_axes")
                    if tomo.zarr_scale is None:
                        tomo.zarr_scale = zarr_result.fields.get("zarr_scale")
            if tomo.zarr_path is None and zarr_path_str:
                tomo.zarr_path = zarr_path_str

            # Step 4: voxel-spacing implied vs MRC -------------------------
            implied: float | None = None
            pixel_size = acq.pixel_size
            voxel_bin = tomo.voxel_bin
            if pixel_size is not None and voxel_bin is not None:
                implied = float(pixel_size) * float(voxel_bin)

            if mrc_voxel_spacing is not None and implied is not None:
                if not _relative_close(implied, mrc_voxel_spacing):
                    severity = "error" if on_voxel_mismatch == "error" else "warning"
                    location = (
                        f"acquisitions.{acq_loc.acquisition_id}"
                        f".tomogram[{tomo_loc.tomogram_id}]"
                        ".voxel_spacing_angstrom"
                    )
                    result.conflicts.append(
                        FieldConflict(
                            location=location,
                            category="voxel_spacing_implied_mismatch",
                            values={
                                "mrc_header": mrc_voxel_spacing,
                                "implied (pixel_size*voxel_bin)": implied,
                            },
                            severity=severity,
                        )
                    )
                    msg = (
                        f"MRC header voxel_spacing_angstrom ({mrc_voxel_spacing}) "
                        f"disagrees with implied pixel_size x voxel_bin ({implied})"
                    )
                    if severity == "error":
                        result.errors.append(f"{location}: {msg}")
                    else:
                        result.warnings.append(
                            ScanWarning(
                                category="voxel_spacing_implied_mismatch",
                                location=location,
                                message=msg,
                            )
                        )

            result.tomogram_aux[
                (sample_id, acq_loc.acquisition_id, tomo_loc.tomogram_id)
            ] = {
                "voxel_spacing_angstrom": mrc_voxel_spacing,
                "voxel_spacing_angstrom_implied": implied,
            }

        # Step 5: derived fields per tomogram -------------------------------
        for tomo in acq_file.tomogram:
            if tomo.is_raw is None:
                tomo.is_raw = tomo.derived_from == []
        # Chromatin.linker_length_fraction: no-op for v1 — the supposed
        # ``sequence_footprint`` source field doesn't exist on Chromatin.

        # Step 6: annotation files ------------------------------------------
        existing_anns = {a.annotation_id: a for a in acq_file.annotation}
        for ann_loc in iter_annotations(acq_loc):
            ann = existing_anns.get(ann_loc.annotation_id)
            if ann is None:
                result.warnings.append(
                    ScanWarning(
                        category="undeclared_annotation_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".annotation[{ann_loc.annotation_id}]"
                        ),
                        message=(
                            f"folder '{ann_loc.annotation_id}' exists on disk but is "
                            "not declared in acquisition.toml — add an [[annotation]] "
                            f"block with id = \"{ann_loc.annotation_id}\""
                        ),
                    )
                )
                continue
            if not ann.files:
                ann.files = sorted(str(p) for p in ann_loc.files)

    # ── Step 7: re-validate ──────────────────────────────────────────────────
    try:
        record = SampleRecord.model_validate(record.model_dump(by_alias=True))
    except Exception as e:  # noqa: BLE001
        result.errors.append(f"re-validation failed: {e}")
        result.record = None
        return result

    result.record = record
    return result


__all__ = [
    "AssemblyResult",
    "FieldConflict",
    "ScanWarning",
    "ScanWarningCategory",
    "assemble_sample",
]
