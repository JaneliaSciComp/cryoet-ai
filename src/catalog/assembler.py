"""Assembler: merges parser outputs for one sample into a validated SampleRecord.

Inputs: a SampleLocation. Outputs: AssemblyResult with the merged record, the
list of structured warnings (per Q7), any cross-source conflicts, and the
structured extras list (passed through from schema.loader for
persistence).

The assembler is the sole creator of ScanWarning objects; persistence is a
dumb writer that stamps detected_at and scan_run_id at insert time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from schema import (
    Acquisition,
    AcquisitionFile,
    PostProcessedTomogram,
    RawTomogram,
    SampleRecord,
)
from schema.loader import ExtrasEntry

from catalog.discovery import (
    SampleLocation,
    iter_acquisitions,
    iter_annotations,
    iter_tomograms,
)
from catalog.parsers.frame_ext import infer_camera
from catalog.parsers.mdoc import parse_acquisition_mdocs
from catalog.parsers.mrc_header import read_mrc_header
from catalog.parsers.ome_zarr import read_zarr_attrs
from catalog.parsers.tilt_series import parse_tilt_series_dir
from catalog.parsers.toml_files import load_sample_toml


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
    "tilt_series_id_collision",
    "tilt_series_layout_unknown",
    "undeclared_tomogram_folder",
    "undeclared_annotation_folder",
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


_TYPO_LOC_RE = re.compile(r"on (\w+) closely matches")
_EXTRA_AT_RE = re.compile(r"extra field '[^']+' at '([^']+)' \(not in schema\)")


def _categorize_loader_warning(s: str) -> ScanWarning:
    """Convert a loader warning string into a structured ScanWarning.

    The loader's warning strings have stable prefixes (verified in
    ``schema/loader.py``):

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


def assemble_sample(sample_loc: SampleLocation) -> AssemblyResult:
    """Assemble one sample's discovery + parser outputs into a SampleRecord.

    Implements the per-sample merge:

    1. Load TOML via the schema loader; bail out (record=None) if the sample
       block is unrecoverable.
    1.5. Synthesize empty AcquisitionFile entries for filesystem acquisitions
       that aren't in record.acquisitions (Frames-only or unparseable
       acquisition.toml). Emit categorized warnings.
    2. Per-acquisition: run MDOC + frame-extension parsers; fill in fields
       on the Acquisition Pydantic model that are still None.
    3. Per-tomogram (raw or post-processed): run MRC header + OME-Zarr
       parsers; fill image_size_*, mrc_path, zarr_path, zarr_axes/scale.
       Only PostProcessedTomogram records ``size_bytes`` (raw has no
       size_bytes field in the schema).
    4. Per-annotation: assign sorted file paths from disk discovery onto
       ``Annotation.files``.
    5. Re-validate the populated record via
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
        )
        new_acquisitions[acq_loc.acquisition_id] = synth

    record = record.model_copy(update={"acquisitions": new_acquisitions})

    # Record the sample directory once so sample-level UI actions (copy path,
    # open in Fileglancer) work even for samples with zero acquisitions.
    # Mirrors the per-acquisition path injection below.
    if record.sample.path is None:
        record.sample.path = str(sample_loc.path)

    # ── Steps 2, 3, 4: walk each acquisition ─────────────────────────────────
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

        # Record the acquisition directory once, regardless of whether the
        # acquisition was synthesized or had an acquisition.toml — powers the
        # UI's copy-path / open-in-file-browser buttons.
        if acq.path is None:
            acq.path = str(acq_loc.path)

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

            # Tilt-series parsing. The acquisition-level MDOC parser above
            # only covers the first MDOC alphabetically; this loop
            # catalogues every series-level MDOC (one record each) and
            # collapses per-tilt MDOC groups (gouauxlab convention) into
            # single records. ``microscope`` / ``camera`` come from
            # acquisition.toml only.
            ts_result = parse_tilt_series_dir(
                acq_loc.frames_dir, acquisition_id=acq_loc.acquisition_id
            )
            for mdoc_path_str, err_msg in ts_result.unreadable:
                result.warnings.append(
                    ScanWarning(
                        category="unparseable_mdoc",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tilt_series[{mdoc_path_str}]"
                        ),
                        message=err_msg,
                    )
                )
            for path_str, msg in ts_result.layout_unknown:
                result.warnings.append(
                    ScanWarning(
                        category="tilt_series_layout_unknown",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tilt_series[{path_str}]"
                        ),
                        message=msg,
                    )
                )
            for collision in ts_result.collisions:
                result.warnings.append(
                    ScanWarning(
                        category="tilt_series_id_collision",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tilt_series[{collision.tilt_series_id}]"
                        ),
                        message=(
                            f"MDOC '{collision.mdoc_path}' shares stem "
                            f"'{collision.original_stem}' with another MDOC in "
                            f"the same acquisition; disambiguated to "
                            f"tilt_series_id='{collision.tilt_series_id}'"
                        ),
                    )
                )
            # Replace any TOML-authored tilt_series list with the parser's
            # output — the scanner is the canonical writer for this field.
            acq_file.tilt_series = ts_result.records

        # Step 3: tomograms (raw + post share one id namespace) -------------
        existing_tomos: dict[str, RawTomogram | PostProcessedTomogram] = {}
        if acq_file.raw_tomogram is not None:
            existing_tomos[acq_file.raw_tomogram.tomogram_id] = acq_file.raw_tomogram
        for t in acq_file.post_processed_tomogram:
            existing_tomos[t.tomogram_id] = t

        for tomo_loc in iter_tomograms(acq_loc):
            tomo = existing_tomos.get(tomo_loc.tomogram_id)
            if tomo is None:
                # Tomogram folder on disk not declared in acquisition.toml.
                # v1 does not synthesize tomograms; warn so a forgotten
                # [raw_tomogram] / [[post_processed_tomogram]] block doesn't
                # go unnoticed.
                result.warnings.append(
                    ScanWarning(
                        category="undeclared_tomogram_folder",
                        location=(
                            f"acquisitions.{acq_loc.acquisition_id}"
                            f".tomogram[{tomo_loc.tomogram_id}]"
                        ),
                        message=(
                            f"folder '{tomo_loc.tomogram_id}' exists on disk but is "
                            "not declared in acquisition.toml — add a [raw_tomogram] "
                            "or [[post_processed_tomogram]] block with "
                            f"id = \"{tomo_loc.tomogram_id}\""
                        ),
                    )
                )
                continue

            if tomo_loc.mrc_files:
                mrc_path_str = str(tomo_loc.mrc_files[0])
                # size_bytes only exists on PostProcessedTomogram.
                if (
                    isinstance(tomo, PostProcessedTomogram)
                    and tomo.size_bytes is None
                ):
                    try:
                        tomo.size_bytes = tomo_loc.mrc_files[0].stat().st_size
                    except OSError:
                        pass
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
                if tomo.mrc_path is None:
                    tomo.mrc_path = mrc_path_str

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
                if tomo.zarr_path is None:
                    tomo.zarr_path = zarr_path_str

        # Step 4: annotation files ------------------------------------------
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

    # ── Step 5: re-validate ──────────────────────────────────────────────────
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
