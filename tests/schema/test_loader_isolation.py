"""Tests for per-acquisition isolation and <FILL IN> placeholder stripping."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from schema.loader import load_sample_record


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def _minimal_sample(root: Path) -> None:
    _write(
        root / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )


def test_one_bad_acquisition_does_not_block_the_rest(tmp_path):
    _minimal_sample(tmp_path)
    # acq_a is a clean, valid acquisition.
    _write(
        tmp_path / "acq_a" / "acquisition.toml",
        """
        [acquisition]
        resolution = 3.5
        """,
    )
    # acq_b has a dangling target_tomogram, so it fails validation.
    _write(
        tmp_path / "acq_b" / "acquisition.toml",
        """
        [acquisition]

        [raw_tomogram]
        id = "tomo_001"

        [[annotation]]
        id = "ann_001"
        target_tomogram = "ghost"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq_a" in result.record.acquisitions
    assert "acq_b" not in result.record.acquisitions
    assert "acq_b" in result.acquisition_errors
    assert "ghost" in result.acquisition_errors["acq_b"]


def test_bad_sample_toml_still_returns_record_none(tmp_path):
    """Regression: an unrecoverable sample.toml continues to produce record=None."""
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("project" in e for e in result.sample_errors)


def test_unparseable_acquisition_toml_lands_in_acquisition_errors(tmp_path):
    _minimal_sample(tmp_path)
    (tmp_path / "acq1").mkdir()
    (tmp_path / "acq1" / "acquisition.toml").write_text("not = = valid\n")
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    assert "TOML parse error" in result.acquisition_errors["acq1"]


def test_fill_in_placeholder_in_sample_toml_warns_and_nones_field(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        description = "<FILL IN>"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert result.record.sample.description is None
    assert any(
        "unfilled <FILL IN> placeholder" in w and "description" in w
        for w in result.warnings
    )


def test_fill_in_placeholder_in_numeric_field_strips_to_none(tmp_path):
    """A <FILL IN> in a numeric field would otherwise fail type coercion;
    the loader strips it to None *before* validation runs.
    """
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        pixel_size = "<FILL IN>"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.record.acquisitions
    assert result.record.acquisitions["acq1"].acquisition.pixel_size is None
    assert any(
        "unfilled <FILL IN> placeholder" in w and "pixel_size" in w
        for w in result.warnings
    )
