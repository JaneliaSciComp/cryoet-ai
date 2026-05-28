"""Tests for cryoet_schema.loader (formerly scripts.validate)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cryoet_schema.loader import load_sample_record
from cryoet_schema.validate import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def _minimal_sample(root: Path, *, project: str = "chromatin") -> Path:
    _write(
        root / "sample.toml",
        f"""
        [sample]
        data_source = "experimental"
        project = "{project}"
        """,
    )
    return root


def _minimal_acquisition(root: Path, name: str = "acq1") -> Path:
    acq_dir = root / name
    _write(acq_dir / "acquisition.toml", "[acquisition]\n")
    return acq_dir


# ── load_sample_record ───────────────────────────────────────────────────────


def test_missing_sample_toml(tmp_path):
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("missing sample.toml" in e for e in result.sample_errors)
    assert result.warnings == []


def test_sample_toml_parse_error(tmp_path):
    (tmp_path / "sample.toml").write_text("this is = = not valid toml\n")
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("TOML parse error" in e for e in result.sample_errors)


def test_acquisition_toml_parse_error(tmp_path):
    """Per-acquisition isolation: a bad acquisition.toml doesn't sink the sample."""
    _minimal_sample(tmp_path)
    (tmp_path / "acq1").mkdir()
    (tmp_path / "acq1" / "acquisition.toml").write_text("not = = valid\n")
    result = load_sample_record(tmp_path)
    assert result.record is not None  # sample-level still validates
    assert "acq1" in result.acquisition_errors
    assert "TOML parse error" in result.acquisition_errors["acq1"]
    assert "acq1" not in result.record.acquisitions


def test_minimal_valid_sample(tmp_path):
    _minimal_sample(tmp_path)
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.warnings == []
    assert result.record is not None
    assert result.record.sample.data_source.value == "experimental"
    assert result.record.sample.project.value == "chromatin"
    assert result.record.sample.sample_id == tmp_path.name
    assert result.record.acquisitions == {}


def test_missing_required_field(tmp_path):
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


def test_invalid_enum_value(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "xray"
        project = "chromatin"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("data_source" in e for e in result.sample_errors)


def test_extra_field_no_typo_only_generic_warning(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        totally_unrelated_key = "foo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.record is not None
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    generic_warnings = [w for w in result.warnings if "not in schema" in w]
    assert typo_warnings == []
    assert any("totally_unrelated_key" in w for w in generic_warnings)


def test_extra_field_typo_produces_suggestion(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        descriptiom = "typo here"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.record is not None
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert len(typo_warnings) == 1
    assert "descriptiom" in typo_warnings[0]
    assert "description" in typo_warnings[0]
    assert "Sample" in typo_warnings[0]


def test_typo_on_nested_model(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [chromatin]
        bufffer = "typo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert any("bufffer" in w and "buffer" in w and "Chromatin" in w for w in typo_warnings)


def test_typo_in_acquisition(tmp_path):
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscoope = "typo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert any("microscoope" in w and "microscope" in w for w in typo_warnings)


def test_typo_warning_preserved_when_validation_fails(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        descriptiom = "typo alongside a hard error"

        [chromatin]
        nucleosome_count = "not-an-int"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("nucleosome_count" in e for e in result.sample_errors)
    typo_warnings = [w for w in result.warnings if "possible typo" in w]
    assert any("descriptiom" in w and "description" in w for w in typo_warnings)


def test_project_block_mismatch_synapse_on_chromatin(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [synapse]
        label_target = "AMPA"
        label_strategy = "single_label"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("chromatin" in e and "synapse" in e for e in result.sample_errors)


def test_simulation_block_rejected_for_cryoet(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [simulation]
        dataset_type = "bulk"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is None
    assert any("experimental" in e and "simulation" in e for e in result.sample_errors)


def test_aunp_block_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [[aunp]]
        size_nm = 5.0
        type = "colloidal"
        fluorophore = "Alexa647"
        concentration_value = 2.5
        concentration_unit = "nM"
        conjugation = "Fab"
        conjugation_target = "GluA2"

        [[aunp]]
        size_nm = 10.0
        type = "cluster"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert len(result.record.aunp) == 2
    assert result.record.aunp[0].size_nm == 5.0
    assert result.record.aunp[0].conjugation_target == "GluA2"
    assert result.record.aunp[1].type == "cluster"


def test_freezing_block_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [freezing]
        grid_type = "Quantifoil R2/2"
        cryoprotectant = "none"
        method = "HPF"
        planchette_size = "3 mm"
        spacer_thickness = "100 um"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert result.record.freezing is not None
    assert result.record.freezing.method == "HPF"
    assert result.record.freezing.planchette_size == "3 mm"


def test_milling_block_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"

        [milling]
        scheme = "cryo-FIB"
        date = 2025-06-15
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert result.record.milling is not None
    assert result.record.milling.scheme == "cryo-FIB"
    assert result.record.milling.date.isoformat() == "2025-06-15"


def test_simulation_sample_happy_path(tmp_path):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"

        [simulation]
        dataset_type = "single_molecule"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.warnings == []
    assert result.record is not None
    assert result.record.sample.data_source.value == "simulation"
    assert result.record.simulation is not None
    assert result.record.simulation.dataset_type == "single_molecule"


def test_acquisition_with_tomogram_and_annotation(tmp_path):
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]
        resolution = 3.5

        [[tomogram]]
        id = "tomo_001"
        pipeline = "AreTomo"

        [[tomogram]]
        id = "tomo_002"
        derived_from = ["tomo_001"]

        [[annotation]]
        id = "ann_001"
        target_tomogram = "tomo_001"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None
    acq = result.record.acquisitions["acq1"]
    assert [t.tomogram_id for t in acq.tomogram] == ["tomo_001", "tomo_002"]
    assert acq.annotation[0].target_tomogram == "tomo_001"


def test_annotation_target_tomogram_missing(tmp_path):
    """Per-acquisition isolation: dangling target_tomogram fails just that acquisition."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[tomogram]]
        id = "tomo_001"

        [[annotation]]
        id = "ann_001"
        target_tomogram = "nonexistent_tomo"
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None  # sample-level still validates
    assert "acq1" in result.acquisition_errors
    assert "nonexistent_tomo" in result.acquisition_errors["acq1"]
    assert "acq1" not in result.record.acquisitions


def test_tomogram_derived_from_unknown(tmp_path):
    """Per-acquisition isolation: dangling derived_from fails just that acquisition."""
    _minimal_sample(tmp_path)
    _write(
        tmp_path / "acq1" / "acquisition.toml",
        """
        [acquisition]

        [[tomogram]]
        id = "tomo_001"
        derived_from = ["ghost"]
        """,
    )
    result = load_sample_record(tmp_path)
    assert result.record is not None
    assert "acq1" in result.acquisition_errors
    assert "ghost" in result.acquisition_errors["acq1"]
    assert "acq1" not in result.record.acquisitions


def test_multiple_acquisitions(tmp_path):
    _minimal_sample(tmp_path)
    _minimal_acquisition(tmp_path, "acq_a")
    _minimal_acquisition(tmp_path, "acq_b")
    result = load_sample_record(tmp_path)
    assert result.sample_errors == []
    assert result.acquisition_errors == {}
    assert result.record is not None
    assert set(result.record.acquisitions) == {"acq_a", "acq_b"}
    for name, acq in result.record.acquisitions.items():
        assert acq.acquisition.acquisition_id == name


# ── main() ───────────────────────────────────────────────────────────────────


def test_main_wrong_argc(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    # argparse writes usage to stderr by default
    assert "usage" in capsys.readouterr().err.lower()


def test_main_not_a_directory(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    rc = main([str(missing)])
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err


def test_main_success(tmp_path, capsys):
    _minimal_sample(tmp_path)
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "OK" in out.out


def test_main_failure_returns_1(tmp_path, capsys):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        """,
    )
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in out.err


def test_main_prints_typo_warning(tmp_path, capsys):
    _write(
        tmp_path / "sample.toml",
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        descriptiom = "typo"
        """,
    )
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "possible typo" in out.out
