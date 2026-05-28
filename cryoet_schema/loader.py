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

from cryoet_schema import (
    AcquisitionFile,
    DataSource,
    Sample,
    SampleRecord,
)


_PLACEHOLDER = "<FILL IN>"


@dataclass
class ExtrasEntry:
    """One top-level unknown key on a validated entity.

    ``entity_type`` is the lowercase table-name string (``"sample"``,
    ``"chromatin"``, ``"label"``, ``"acquisition"``, ``"raw_tomogram"``,
    ``"post_processed_tomogram"``, ``"annotation"``, …). ``entity_pk`` is the parent row's PK as a tuple
    of native Python values (e.g. ``("my_sample",)`` for ``chromatin``,
    ``("my_sample", 2)`` for the third label entry, ``("my_sample",
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


def _md_source_ref_error(
    acq: AcquisitionFile, valid_md_run_ids: set[str]
) -> str | None:
    """Error string if the acquisition's ``md_source.md_run_id`` is set but
    matches no ``[[md_run]]`` id declared in ``sample.toml``.

    This is the one reference that crosses files (acquisition.toml ->
    sample.toml), so it can't live on ``AcquisitionFile`` and isn't enforced
    at ``SampleRecord`` level (which would fail the whole sample). The loader
    checks it during the per-acquisition pass and routes a dangling ref to
    that acquisition's ``acquisition_errors``, preserving isolation.
    """
    src = acq.md_source
    if src is None or src.md_run_id is None:
        return None
    if src.md_run_id not in valid_md_run_ids:
        return (
            f"md_source.md_run_id '{src.md_run_id}' does not match any "
            f"[[md_run]] id in sample.toml"
        )
    return None


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
    if et == "label":
        # entity_pk = (sample_id, index)
        return f"label[{pk[1]}]"
    if et == "md_run":
        # entity_pk = (sample_id, md_run_id)
        return f"md_run[{pk[1]}]"
    if et == "acquisition":
        # entity_pk = (sample_id, acq_id)
        return f"acquisitions.{pk[1]}.acquisition"
    if et == "tilt_series":
        # entity_pk = (sample_id, acq_id)
        return f"acquisitions.{pk[1]}.tilt_series"
    if et == "md_source":
        # entity_pk = (sample_id, acq_id)
        return f"acquisitions.{pk[1]}.md_source"
    if et == "raw_tomogram":
        # entity_pk = (sample_id, acq_id, tomogram_id)
        return f"acquisitions.{pk[1]}.raw_tomogram"
    if et == "post_processed_tomogram":
        # entity_pk = (sample_id, acq_id, tomogram_id)
        return f"acquisitions.{pk[1]}.post_processed_tomogram[{pk[2]}]"
    if et == "annotation":
        # entity_pk = (sample_id, acq_id, annotation_id)
        return f"acquisitions.{pk[1]}.annotation[{pk[2]}]"
    return et


# ── walker ───────────────────────────────────────────────────────────────────


def _walk_extras(record: SampleRecord) -> list[ExtrasEntry]:
    """Walk ``record`` and emit one ExtrasEntry per top-level unknown key.

    Per-container PK rules per §4.4.1. Reaches into the tomogram /
    ``Annotation.annotation_id`` for the child PK rather than using the
    list index — this is a regression-tested invariant.
    """
    out: list[ExtrasEntry] = []
    sample_id = record.sample.sample_id  # always set by the loader

    # sample
    for k, v in (record.sample.model_extra or {}).items():
        out.append(ExtrasEntry("sample", (sample_id,), k, v))

    # optional 1:1 sub-entities
    for attr in ("chromatin", "simulation", "fiducial", "freezing", "milling"):
        sub = getattr(record, attr)
        if sub is not None:
            for k, v in (sub.model_extra or {}).items():
                out.append(ExtrasEntry(attr, (sample_id,), k, v))

    # label - positional
    for i, label in enumerate(record.label):
        for k, v in (label.model_extra or {}).items():
            out.append(ExtrasEntry("label", (sample_id, i), k, v))

    # md_run - id-keyed (folder name), like tomograms
    for run in record.md_run:
        for k, v in (run.model_extra or {}).items():
            out.append(ExtrasEntry("md_run", (sample_id, run.md_run_id), k, v))

    # acquisitions - dict
    for acq_id, acq_file in record.acquisitions.items():
        # AcquisitionFile.model_extra itself is intentionally NOT walked.
        for k, v in (acq_file.acquisition.model_extra or {}).items():
            out.append(ExtrasEntry("acquisition", (sample_id, acq_id), k, v))
        if acq_file.tilt_series is not None:
            for k, v in (acq_file.tilt_series.model_extra or {}).items():
                out.append(
                    ExtrasEntry("tilt_series", (sample_id, acq_id), k, v)
                )
        if acq_file.md_source is not None:
            for k, v in (acq_file.md_source.model_extra or {}).items():
                out.append(
                    ExtrasEntry("md_source", (sample_id, acq_id), k, v)
                )
        if acq_file.raw_tomogram is not None:
            raw = acq_file.raw_tomogram
            for k, v in (raw.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "raw_tomogram", (sample_id, acq_id, raw.tomogram_id), k, v
                    )
                )
        for tomo in acq_file.post_processed_tomogram:
            for k, v in (tomo.model_extra or {}).items():
                out.append(
                    ExtrasEntry(
                        "post_processed_tomogram",
                        (sample_id, acq_id, tomo.tomogram_id),
                        k,
                        v,
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
    # the [sample] table; the rest of sample.toml ([chromatin], [label],
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

    # md_run ids declared in sample.toml (raw, by TOML `id` alias). Used to
    # validate each acquisition's md_source reference below. A malformed or
    # duplicate md_run id is caught later by SampleRecord validation and fails
    # the whole sample; here we only need the declared id set.
    valid_md_run_ids = {
        run["id"]
        for run in sample_data.get("md_run", [])
        if isinstance(run, dict) and isinstance(run.get("id"), str)
    }

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
            # The dangling-md_run-ref check only applies to simulation samples.
            # On experimental samples an md_source block is a category error
            # (no md_runs exist), left for SampleRecord to reject whole-sample
            # with a clear message — don't pre-empt it here with a misleading
            # "no matching md_run" error.
            ref_error = None
            if sample_model.data_source == DataSource.simulation:
                ref_error = _md_source_ref_error(acq_model, valid_md_run_ids)
            if ref_error is not None:
                result.acquisition_errors[acq_name] = ref_error
            else:
                validated_acqs[acq_name] = acq_model

    # Build the full record. Pass already-validated acquisitions through
    # by dumping back to dict (preserves alias round-tripping for the
    # tomogram / annotation `id` alias) and re-validating end-to-end so
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
