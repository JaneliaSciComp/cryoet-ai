"""Library for loading and validating a cryoET sample directory.

The pure-library counterpart of ``cryoet_schema.validate``. Provides
``load_sample_record(sample_dir)`` which:

- parses ``sample.toml`` and validates it as a ``Sample``;
- parses each ``*/acquisition.toml`` and validates each *independently*
  as an ``AcquisitionFile`` so a single bad acquisition doesn't black-hole
  the rest of the sample (per-acquisition isolation, §4.4.1);
- strips ``"<FILL IN>"`` placeholders to ``None`` before validation,
  collecting their dotted paths into ``warnings``;
- assembles a final ``SampleRecord`` from the ``Sample`` plus successfully
  validated acquisitions;
- walks the assembled record for ``model_extra`` keys and emits one
  ``ExtrasEntry`` per top-level unknown key per visited entity.

The result is a ``LoadResult`` consumed both by the validate CLI
(``cryoet_schema/validate.py``) and by the catalog scanner downstream.
"""

from __future__ import annotations

import tomllib
import warnings as _warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from rapidfuzz import process

from cryoet_schema import (
    AcquisitionFile,
    Sample,
    SampleRecord,
)


_PLACEHOLDER = "<FILL IN>"

# Subdirectory layouts probed when cross-checking tomogram/annotation ids
# against folders on disk. Tomograms live under one of two layouts (real
# data vs simulated); annotations live under one. Kept in sync with
# cryoet_catalog.discovery.iter_tomograms / iter_annotations.
_TOMOGRAM_PARENT_DIRS = ("Reconstructions/Tomograms", "SyntheticCryoET")
_ANNOTATION_PARENT_DIRS = ("Reconstructions/Annotations",)
_FOLDER_SUGGEST_CUTOFF = 80


@dataclass
class ExtrasEntry:
    """One top-level unknown key on a validated entity.

    ``entity_type`` is the lowercase table-name string (``"sample"``,
    ``"chromatin"``, ``"aunp"``, ``"acquisition"``, ``"tomogram"``,
    ``"annotation"``, …). ``entity_pk`` is the parent row's PK as a tuple
    of native Python values (e.g. ``("my_sample",)`` for ``chromatin``,
    ``("my_sample", 2)`` for the third aunp entry, ``("my_sample",
    "Position_86", "my_tomo")`` for a tomogram). ``key`` is the unknown
    top-level TOML key. ``value`` is the raw Python value Pydantic stored
    on ``model_extra`` (may be a nested dict — inner keys are NOT
    flattened).
    """

    entity_type: str
    entity_pk: tuple
    key: str
    value: Any


@dataclass
class LoadResult:
    """Outcome of ``load_sample_record``.

    ``record`` is ``None`` only when ``sample.toml`` itself is missing,
    unparseable, or fails ``Sample`` validation — i.e. the sample is
    unrecoverable. A bad ``acquisition.toml`` produces a non-``None``
    record with that acquisition absent and its error in
    ``acquisition_errors``.
    """

    record: SampleRecord | None
    sample_errors: list[str] = field(default_factory=list)
    acquisition_errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extras: list[ExtrasEntry] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────


def _format_error_loc(loc: tuple) -> str:
    return ".".join(str(x) for x in loc)


def _strip_placeholders(value: Any, path: str, warnings_out: list[str]) -> Any:
    """Recursively replace ``"<FILL IN>"`` strings with ``None``.

    Walks dicts and lists. Records the dotted ``path`` of every
    replacement into ``warnings_out``. Returns the (possibly mutated)
    value — for dicts/lists the same instance is mutated in place and
    returned for convenience.
    """
    if isinstance(value, dict):
        for k, v in list(value.items()):
            child_path = f"{path}.{k}" if path else str(k)
            value[k] = _strip_placeholders(v, child_path, warnings_out)
        return value
    if isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = _strip_placeholders(v, f"{path}[{i}]", warnings_out)
        return value
    if isinstance(value, str) and value == _PLACEHOLDER:
        warnings_out.append(f"{path}: unfilled <FILL IN> placeholder")
        return None
    return value


def _format_validation_errors(prefix: str, exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = _format_error_loc(err["loc"])
        if prefix and loc:
            out.append(f"{prefix}.{loc}: {err['msg']}")
        elif prefix:
            out.append(f"{prefix}: {err['msg']}")
        else:
            out.append(f"{loc}: {err['msg']}")
    return out


def _format_extras_location(entry: ExtrasEntry) -> str:
    """Flatten an ExtrasEntry to a human-readable path.

    Used by the validate CLI for warning printing and by the loader
    itself when emitting per-entry "extra field at" warnings.
    """
    et = entry.entity_type
    pk = entry.entity_pk
    if et == "sample":
        return "sample"
    if et in ("chromatin", "synapse", "simulation", "freezing", "milling"):
        return et
    if et == "aunp":
        # entity_pk = (sample_id, index)
        return f"aunp[{pk[1]}]"
    if et == "acquisition":
        # entity_pk = (sample_id, acq_id)
        return f"acquisitions.{pk[1]}.acquisition"
    if et == "tomogram":
        # entity_pk = (sample_id, acq_id, tomogram_id)
        return f"acquisitions.{pk[1]}.tomogram[{pk[2]}]"
    if et == "annotation":
        # entity_pk = (sample_id, acq_id, annotation_id)
        return f"acquisitions.{pk[1]}.annotation[{pk[2]}]"
    if et == "tilt_series":
        # entity_pk = (sample_id, acq_id, tilt_series_id)
        return f"acquisitions.{pk[1]}.tilt_series[{pk[2]}]"
    return et


# ── id ↔ folder cross-check ──────────────────────────────────────────────────


def _candidate_folder_names(acq_dir: Path, parent_dirs: tuple[str, ...]) -> list[str]:
    """Return on-disk folder names from any of the candidate parent dirs.

    Used to suggest the closest match when a TOML-declared id has no
    matching folder. Missing parents contribute nothing rather than
    erroring.
    """
    names: list[str] = []
    for sub in parent_dirs:
        d = acq_dir / sub
        if d.is_dir():
            names.extend(p.name for p in d.iterdir() if p.is_dir())
    return names


def _has_matching_folder(
    acq_dir: Path, parent_dirs: tuple[str, ...], entity_id: str
) -> bool:
    return any((acq_dir / sub / entity_id).is_dir() for sub in parent_dirs)


def _check_id_folder_alignment(
    acq_dir: Path, acq_model: AcquisitionFile
) -> list[str]:
    """Verify each declared tomogram/annotation id has a matching folder.

    The TOML-authored ``id`` field MUST equal the folder's directory name
    on disk so the two cannot drift. If no matching folder exists, return
    a one-line error per offender (with a fuzzy suggestion when the
    closest folder name is plausibly the intended target).
    """
    errors: list[str] = []

    tomo_candidates = _candidate_folder_names(acq_dir, _TOMOGRAM_PARENT_DIRS)
    for tomo in acq_model.tomogram:
        if _has_matching_folder(acq_dir, _TOMOGRAM_PARENT_DIRS, tomo.tomogram_id):
            continue
        joined_parents = " or ".join(repr(p) for p in _TOMOGRAM_PARENT_DIRS)
        msg = (
            f"tomogram[{tomo.tomogram_id}]: id has no matching folder under "
            f"{joined_parents}; "
            f"the id must equal the tomogram's directory name"
        )
        match = process.extractOne(
            tomo.tomogram_id, tomo_candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
        )
        if match:
            msg += f" (did you mean '{match[0]}'?)"
        errors.append(msg)

    ann_candidates = _candidate_folder_names(acq_dir, _ANNOTATION_PARENT_DIRS)
    for ann in acq_model.annotation:
        if _has_matching_folder(acq_dir, _ANNOTATION_PARENT_DIRS, ann.annotation_id):
            continue
        msg = (
            f"annotation[{ann.annotation_id}]: id has no matching folder under "
            f"{_ANNOTATION_PARENT_DIRS[0]!r}; "
            f"the id must equal the annotation's directory name"
        )
        match = process.extractOne(
            ann.annotation_id, ann_candidates, score_cutoff=_FOLDER_SUGGEST_CUTOFF
        )
        if match:
            msg += f" (did you mean '{match[0]}'?)"
        errors.append(msg)

    return errors


# ── walker ───────────────────────────────────────────────────────────────────


def _walk_extras(record: SampleRecord) -> list[ExtrasEntry]:
    """Walk ``record`` and emit one ExtrasEntry per top-level unknown key.

    Per-container PK rules per §4.4.1. Reaches into ``Tomogram.tomogram_id``
    / ``Annotation.annotation_id`` for the child PK rather than using the
    list index — this is a regression-tested invariant.
    """
    out: list[ExtrasEntry] = []
    sample_id = record.sample.sample_id  # always set by the loader

    # sample
    for k, v in (record.sample.model_extra or {}).items():
        out.append(ExtrasEntry("sample", (sample_id,), k, v))

    # optional 1:1 sub-entities
    for attr in ("chromatin", "synapse", "simulation", "freezing", "milling"):
        sub = getattr(record, attr)
        if sub is not None:
            for k, v in (sub.model_extra or {}).items():
                out.append(ExtrasEntry(attr, (sample_id,), k, v))

    # aunp - positional
    for i, aunp in enumerate(record.aunp):
        for k, v in (aunp.model_extra or {}).items():
            out.append(ExtrasEntry("aunp", (sample_id, i), k, v))

    # acquisitions - dict
    for acq_id, acq_file in record.acquisitions.items():
        # AcquisitionFile.model_extra itself is intentionally NOT walked.
        for k, v in (acq_file.acquisition.model_extra or {}).items():
            out.append(ExtrasEntry("acquisition", (sample_id, acq_id), k, v))
        for tomo in acq_file.tomogram:
            for k, v in (tomo.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "tomogram", (sample_id, acq_id, tomo.tomogram_id), k, v
                    )
                )
        for ann in acq_file.annotation:
            for k, v in (ann.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "annotation",
                        (sample_id, acq_id, ann.annotation_id),
                        k,
                        v,
                    )
                )
        for ts in acq_file.tilt_series:
            # ``tilt_series_id`` may legitimately be None on TOML-authored rows
            # (the scanner is the canonical writer); only emit extras when an
            # id is present so the PK tuple is well-formed.
            if ts.tilt_series_id is None:
                continue
            for k, v in (ts.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "tilt_series",
                        (sample_id, acq_id, ts.tilt_series_id),
                        k,
                        v,
                    )
                )
    return out


# ── main entry point ─────────────────────────────────────────────────────────


def load_sample_record(sample_dir: Path) -> LoadResult:
    """Load and validate a sample directory; return a ``LoadResult``.

    Per-acquisition isolation: a bad ``acquisition.toml`` (parse error
    or validation failure) appears in ``acquisition_errors`` and is
    skipped; the rest of the sample still validates and the returned
    ``record.acquisitions`` excludes the bad acquisition.

    ``"<FILL IN>"`` placeholder strings are replaced with ``None``
    before Pydantic validation runs; each replacement emits a warning
    of the form ``"<dotted.path>: unfilled <FILL IN> placeholder"``.
    """
    result = LoadResult(record=None)

    sample_toml = sample_dir / "sample.toml"
    if not sample_toml.is_file():
        result.sample_errors.append(f"missing sample.toml at {sample_toml}")
        return result

    try:
        with sample_toml.open("rb") as f:
            sample_data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        result.sample_errors.append(f"sample.toml: TOML parse error: {e}")
        return result

    # Strip <FILL IN> placeholders from sample.toml before pydantic runs.
    _strip_placeholders(sample_data, "", result.warnings)

    # Inject sample_id from the directory name (preserve _minimal_sample
    # behaviour from the old script).
    sample_data.setdefault("sample", {})["sample_id"] = sample_dir.name

    # Validate the sample-level portion. The Sample model only consumes
    # the [sample] table; the rest of sample.toml ([chromatin], [aunp],
    # etc.) is handled later by SampleRecord.model_validate of the full
    # dict.
    sample_block = sample_data.get("sample", {})
    sample_model: Sample | None = None
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always", UserWarning)
        try:
            sample_model = Sample.model_validate(sample_block)
        except ValidationError as e:
            result.sample_errors.extend(_format_validation_errors("sample", e))
    for w in caught:
        if issubclass(w.category, UserWarning):
            result.warnings.append(str(w.message))

    if sample_model is None:
        return result

    # Per-acquisition: parse, strip placeholders, validate independently.
    validated_acqs: dict[str, AcquisitionFile] = {}
    for acq_toml in sorted(sample_dir.glob("*/acquisition.toml")):
        acq_name = acq_toml.parent.name
        try:
            with acq_toml.open("rb") as f:
                acq_data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            result.acquisition_errors[acq_name] = f"TOML parse error: {e}"
            continue

        _strip_placeholders(
            acq_data, f"acquisitions.{acq_name}", result.warnings
        )
        acq_data.setdefault("acquisition", {})["acquisition_id"] = acq_name

        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always", UserWarning)
            try:
                acq_model = AcquisitionFile.model_validate(acq_data)
            except ValidationError as e:
                msgs = _format_validation_errors("", e)
                result.acquisition_errors[acq_name] = "; ".join(msgs)
                acq_model = None
        for w in caught:
            if issubclass(w.category, UserWarning):
                result.warnings.append(str(w.message))

        if acq_model is not None:
            layout_errors = _check_id_folder_alignment(acq_toml.parent, acq_model)
            if layout_errors:
                joined = "; ".join(layout_errors)
                existing = result.acquisition_errors.get(acq_name)
                result.acquisition_errors[acq_name] = (
                    f"{existing}; {joined}" if existing else joined
                )
            else:
                validated_acqs[acq_name] = acq_model

    # Build the full record. Pass already-validated acquisitions through
    # by dumping back to dict (preserves alias round-tripping for the
    # Tomogram / Annotation `id` alias) and re-validating end-to-end so
    # that SampleRecord-level model validators (project/data_source
    # cross-checks, acquisition-name collisions) run against assembled
    # state.
    merged = {
        **sample_data,
        "acquisitions": {
            acq_id: acq.model_dump(by_alias=True)
            for acq_id, acq in validated_acqs.items()
        },
    }
    merged["sample"] = sample_data["sample"]

    # Track warnings already captured (sample-block + per-acquisition)
    # so that the final SampleRecord pass — which re-walks the same
    # sub-models — doesn't re-emit duplicates.
    already = set(result.warnings)

    record: SampleRecord | None = None
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always", UserWarning)
        try:
            record = SampleRecord.model_validate(merged)
        except ValidationError as e:
            result.sample_errors.extend(_format_validation_errors("", e))
    for w in caught:
        if not issubclass(w.category, UserWarning):
            continue
        msg = str(w.message)
        if msg in already:
            continue
        result.warnings.append(msg)
        already.add(msg)

    if record is None:
        return result

    result.record = record
    result.extras = _walk_extras(record)

    # Emit a generic "extra field at <loc> (not in schema)" warning for
    # every extras entry that did NOT already produce a typo warning.
    # Matches the post-processing in the old scripts/validate.py
    # (lines 125-130).
    typo_keys = {
        _extract_typo_field(w)
        for w in result.warnings
        if "possible typo" in w
    }
    typo_keys.discard(None)
    for entry in result.extras:
        if entry.key in typo_keys:
            continue
        loc = _format_extras_location(entry)
        result.warnings.append(
            f"extra field '{entry.key}' at '{loc}' (not in schema)"
        )

    return result


def _extract_typo_field(message: str) -> str | None:
    """Pull the unknown field name out of a typo-warning message.

    Messages are formatted as: ``"extra field 'X' on Y closely matches
    known field 'Z' (similarity N); possible typo"``.
    """
    marker = "extra field '"
    if not message.startswith(marker):
        return None
    rest = message[len(marker):]
    end = rest.find("'")
    if end < 0:
        return None
    return rest[:end]
