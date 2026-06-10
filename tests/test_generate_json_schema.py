"""Tests for schema.generate_json_schema and the committed schemas."""

from __future__ import annotations

import json
from pathlib import Path

from schema import AcquisitionFile, SampleRecord
from schema.generate_json_schema import (
    _ACQUISITION_FILENAME,
    _DEFAULT_OUT,
    main,
    strip_nullable,
)


def test_writes_valid_json_schema_to_given_path(tmp_path, capsys):
    out = tmp_path / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    assert out.is_file()
    loaded = json.loads(out.read_text())
    assert loaded == strip_nullable(SampleRecord.model_json_schema())
    captured = capsys.readouterr().out
    assert "wrote" in captured


def test_writes_acquisition_schema_alongside(tmp_path):
    out = tmp_path / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    acquisition_out = tmp_path / _ACQUISITION_FILENAME
    assert acquisition_out.is_file()
    assert json.loads(acquisition_out.read_text()) == strip_nullable(
        AcquisitionFile.model_json_schema()
    )


def test_creates_parent_directories(tmp_path):
    out = tmp_path / "nested" / "dir" / "schema.json"
    rc = main([str(out)])
    assert rc == 0
    assert out.is_file()
    json.loads(out.read_text())


def test_strip_nullable_collapses_optional_scalar():
    schema = {
        "anyOf": [{"type": "integer"}, {"type": "null"}],
        "default": None,
        "title": "Nucleosome Count",
    }
    assert strip_nullable(schema) == {
        "type": "integer",
        "title": "Nucleosome Count",
    }


def test_strip_nullable_preserves_multi_branch_anyof():
    schema = {
        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
        "default": None,
    }
    assert strip_nullable(schema) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_committed_schema_matches_pydantic_models():
    """Guard against drift between schema/schema.json and SampleRecord.

    Regenerate with: `pixi run json-schema`.
    """
    committed = json.loads(Path(_DEFAULT_OUT).read_text())
    expected = strip_nullable(SampleRecord.model_json_schema())
    assert committed == expected, (
        "schema/schema.json is out of sync with SampleRecord. "
        "Run `pixi run json-schema` to regenerate."
    )


def test_committed_acquisition_schema_matches_pydantic_models():
    """Guard against drift between acquisition.schema.json and AcquisitionFile.

    Regenerate with: `pixi run json-schema`.
    """
    committed_path = Path(_DEFAULT_OUT).parent / _ACQUISITION_FILENAME
    committed = json.loads(committed_path.read_text())
    expected = strip_nullable(AcquisitionFile.model_json_schema())
    assert committed == expected, (
        "schema/acquisition.schema.json is out of sync with AcquisitionFile. "
        "Run `pixi run json-schema` to regenerate."
    )
