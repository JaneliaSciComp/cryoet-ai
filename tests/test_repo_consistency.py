"""Drift guards tying the hand-edited artifacts back to schema.py.

These tests fail loudly (with a fix hint) whenever a change to schema.py or
a template is not mirrored into the doc / starter-copy / README. They are the
safety net for the "edit schema.py -> sync -> test" maintenance loop.
"""

from __future__ import annotations

import enum
import typing
from pathlib import Path

from cryoet_schema import (
    Acquisition,
    Annotation,
    Label,
    Fiducial,
    Chromatin,
    DataSource,
    Freezing,
    Milling,
    PostProcessedTomogram,
    Project,
    RawTomogram,
    Sample,
    Simulation,
)
from cryoet_schema.sync_templates import TEMPLATE_PAIRS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_INFO = _REPO_ROOT / "cryoet_schema" / "schema_info.md"
_README = _REPO_ROOT / "README.md"

# Leaf entity models whose fields map 1:1 to documented table rows. The
# container models (SampleRecord, AcquisitionFile) are excluded: their field
# names are TOML table names, not documented columns.
_ENTITY_MODELS = [
    Sample,
    Simulation,
    Chromatin,
    Label,
    Fiducial,
    Freezing,
    Milling,
    Acquisition,
    RawTomogram,
    PostProcessedTomogram,
    Annotation,
]


def test_starter_templates_in_sync():
    """Each starter-directory copy must equal its canonical template."""
    for canonical, copy in TEMPLATE_PAIRS:
        assert copy.is_file(), f"missing starter copy {copy}"
        assert copy.read_text() == canonical.read_text(), (
            f"{copy.relative_to(_REPO_ROOT)} differs from "
            f"{canonical.relative_to(_REPO_ROOT)}. "
            "Run `pixi run sync-templates` to regenerate."
        )


def test_schema_info_documents_every_field():
    """Every field on every entity model must appear in schema_info.md."""
    doc = _SCHEMA_INFO.read_text()
    missing: list[str] = []
    for model in _ENTITY_MODELS:
        for field_name in model.model_fields:
            if f"`{field_name}`" not in doc:
                missing.append(f"{model.__name__}.{field_name}")
    assert not missing, (
        "fields present in schema.py but undocumented in schema_info.md: "
        + ", ".join(missing)
    )


def _enum_types_in(annotation) -> set[type]:
    found: set[type] = set()
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        found.add(annotation)
    for arg in typing.get_args(annotation):
        found |= _enum_types_in(arg)
    return found


def test_readme_enums_claim_holds():
    """README states data_source/project are the only enums."""
    enums: set[type] = set()
    for model in _ENTITY_MODELS:
        for field in model.model_fields.values():
            enums |= _enum_types_in(field.annotation)
    assert enums == {DataSource, Project}, (
        "the set of enum types changed; README 'Schema rules' claims "
        "data_source and project are the only enums. Update README.md. "
        f"Found: {sorted(e.__name__ for e in enums)}"
    )


def test_readme_required_fields_claim_holds():
    """README states data_source/project are the only required sample fields."""
    required = {n for n, f in Sample.model_fields.items() if f.is_required()}
    assert required == {"data_source", "project"}, (
        "Sample's required fields changed; README 'Required fields' claims "
        "only data_source and project are required. Update README.md. "
        f"Found: {sorted(required)}"
    )
