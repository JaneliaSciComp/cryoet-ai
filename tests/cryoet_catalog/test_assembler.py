"""Tests for cryoet_catalog.assembler."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import mrcfile
import numpy as np
import pytest

from cryoet_catalog.assembler import (
    AssemblyResult,
    FieldConflict,
    ScanWarning,
    _relative_close,
    assemble_sample,
)
from cryoet_catalog.discovery import SampleLocation, iter_samples

FIXTURES = Path(__file__).parent / "fixtures"


# ── helpers ──────────────────────────────────────────────────────────────────


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(content).lstrip())


def _make_mrc(p: Path, shape=(4, 4, 4), voxel_size_x: float = 11.7197) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with mrcfile.new(str(p), overwrite=True) as m:
        m.set_data(np.zeros(shape, dtype=np.float32))
        m.voxel_size = voxel_size_x  # broadcast to xyz


def _make_zattrs(zarr_dir: Path, scale=(11.72, 11.72, 11.72)) -> None:
    zarr_dir.mkdir(parents=True, exist_ok=True)
    s = list(scale)
    (zarr_dir / ".zattrs").write_text(
        '{"multiscales": [{"axes": ['
        '{"name": "z"}, {"name": "y"}, {"name": "x"}], '
        '"datasets": [{"path": "0", "coordinateTransformations": '
        f'[{{"type": "scale", "scale": {s}}}]}}]}}]}}'
    )


def _sample_loc(sample_dir: Path) -> SampleLocation:
    return SampleLocation(
        path=sample_dir,
        sample_id=sample_dir.name,
        sample_toml=sample_dir / "sample.toml",
    )


# ── tests ────────────────────────────────────────────────────────────────────


def test_happy_path_chromatin_fixture():
    samples = {s.sample_id: s for s in iter_samples(FIXTURES)}
    sample_loc = samples["sample_chromatin"]
    result = assemble_sample(sample_loc)

    assert isinstance(result, AssemblyResult)
    assert result.errors == []
    assert result.record is not None
    assert result.record.sample.sample_id == "sample_chromatin"

    acqs = result.record.acquisitions
    assert "Position_86" in acqs
    assert "Position_87" in acqs  # synthesized — Frames-only

    # Position_87 should produce a missing_acquisition_toml warning
    missing = [
        w
        for w in result.warnings
        if w.category == "missing_acquisition_toml"
        and "Position_87" in w.location
    ]
    assert len(missing) == 1

    # Position_86 — MDOC values populated
    p86 = acqs["Position_86"].acquisition
    assert p86.pixel_size == 2.93
    assert p86.voltage == 300.0

    # Tomogram populated from MRC + zarr parsers
    tomos = {t.tomogram_id: t for t in acqs["Position_86"].tomogram}
    assert "bp_3dctf_bin4" in tomos
    tomo = tomos["bp_3dctf_bin4"]
    assert tomo.image_size_x is not None
    assert tomo.image_size_x == 4
    assert tomo.mrc_path is not None
    assert tomo.zarr_path is not None
    assert tomo.zarr_axes == "zyx"
    assert tomo.zarr_scale == [11.72, 11.72, 11.72]
    assert tomo.is_raw is True  # derived_from == []

    aux_key = ("sample_chromatin", "Position_86", "bp_3dctf_bin4")
    assert aux_key in result.tomogram_aux
    aux = result.tomogram_aux[aux_key]
    assert aux["voxel_spacing_angstrom"] == pytest.approx(11.7197, rel=1e-4)
    assert aux["voxel_spacing_angstrom_implied"] == pytest.approx(2.93 * 4)

    # implied vs MRC are within 1e-3 relative — no mismatch warning
    assert not any(
        w.category == "voxel_spacing_implied_mismatch" for w in result.warnings
    )
    assert not any(
        c.category == "voxel_spacing_implied_mismatch" for c in result.conflicts
    )

    # Annotation files populated
    anns = {a.annotation_id: a for a in acqs["Position_86"].annotation}
    assert "membrain_seg_v10" in anns
    files = anns["membrain_seg_v10"].files
    assert files, "annotation files should be populated from disk"
    assert any(f.endswith("segmentation.mrc") for f in files)
    assert any(f.endswith("metadata.json") for f in files)
    assert files == sorted(files)


def _build_basic_cryoet_sample(
    sample_dir: Path,
    *,
    voxel_bin: int,
    mrc_voxel: float,
    pixel_size: float = 2.93,
    voltage: float = 300.0,
    extra_sample_block: str = "",
) -> SampleLocation:
    _write(
        sample_dir / "sample.toml",
        f"""
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        description = "test"
        {extra_sample_block}
        """,
    )
    _write(
        sample_dir / "Pos1" / "acquisition.toml",
        f"""
        [acquisition]
        microscope = "Krios"

        [[tomogram]]
        id = "tomo1"
        voxel_bin = {voxel_bin}
        """,
    )
    _write(
        sample_dir / "Pos1" / "Frames" / "001.mdoc",
        f"""
        PixelSpacing = {pixel_size}
        Voltage = {voltage}

        [ZValue = 0]
        TiltAngle = -60.0
        ExposureDose = 0.5
        """,
    )
    # representative frame
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")
    tomo_dir = sample_dir / "Pos1" / "Reconstructions" / "Tomograms" / "tomo1"
    _make_mrc(tomo_dir / "recon.mrc", voxel_size_x=mrc_voxel)
    _make_zattrs(tomo_dir / "recon.ome.zarr", scale=(mrc_voxel, mrc_voxel, mrc_voxel))
    return _sample_loc(sample_dir)


def test_voxel_mismatch_fixture_relative_tolerance(tmp_path):
    """pixel_size=2.93, voxel_bin=16, MRC voxel=46.8788 — within relative tolerance."""
    sample_dir = tmp_path / "sample_test"
    loc = _build_basic_cryoet_sample(
        sample_dir, voxel_bin=16, mrc_voxel=46.8788
    )
    result = assemble_sample(loc)

    assert result.errors == []
    # implied = 46.88, MRC = 46.8788 — relative diff ~2.6e-5 < 1e-3
    assert _relative_close(46.88, 46.8788)
    assert not any(
        w.category == "voxel_spacing_implied_mismatch" for w in result.warnings
    )
    assert not any(
        c.category == "voxel_spacing_implied_mismatch" for c in result.conflicts
    )


def test_voxel_mismatch_actually_mismatches(tmp_path):
    sample_dir = tmp_path / "sample_test"
    loc = _build_basic_cryoet_sample(sample_dir, voxel_bin=4, mrc_voxel=50.0)
    result = assemble_sample(loc)

    # implied = 11.72, MRC = 50.0 — clearly outside tolerance
    mismatches = [
        c
        for c in result.conflicts
        if c.category == "voxel_spacing_implied_mismatch"
    ]
    assert len(mismatches) == 1
    conflict = mismatches[0]
    assert conflict.severity == "warning"
    assert conflict.values["mrc_header"] == pytest.approx(50.0)
    assert conflict.values["implied (pixel_size*voxel_bin)"] == pytest.approx(
        11.72
    )

    warnings = [
        w
        for w in result.warnings
        if w.category == "voxel_spacing_implied_mismatch"
    ]
    assert len(warnings) == 1
    assert "tomogram[tomo1]" in warnings[0].location
    # warn-mode: errors stays empty
    assert result.errors == []


def test_voxel_mismatch_on_error_raises_to_errors(tmp_path):
    sample_dir = tmp_path / "sample_test"
    loc = _build_basic_cryoet_sample(sample_dir, voxel_bin=4, mrc_voxel=50.0)
    result = assemble_sample(loc, on_voxel_mismatch="error")

    # Error mode promotes the mismatch to result.errors and conflict.severity.
    assert len(result.errors) >= 1
    assert any("voxel_spacing_angstrom" in e for e in result.errors)
    mismatches = [
        c
        for c in result.conflicts
        if c.category == "voxel_spacing_implied_mismatch"
    ]
    assert len(mismatches) == 1
    assert mismatches[0].severity == "error"
    # No warning emitted in error mode
    assert not any(
        w.category == "voxel_spacing_implied_mismatch" for w in result.warnings
    )


def test_simulation_skips_voxel_check(tmp_path):
    """Simulation samples have no MDOC pixel_size, so no implied value, so no check."""
    sample_dir = tmp_path / "sample_sim"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "simulation"
        project = "chromatin"

        [simulation]
        dataset_type = "test"
        """,
    )
    _write(
        sample_dir / "Pos1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[tomogram]]
        id = "tomo1"
        voxel_bin = 4
        """,
    )
    # Note: NO Frames/ dir — no mdoc, so no pixel_size populated.
    tomo_dir = sample_dir / "Pos1" / "SyntheticCryoET" / "tomo1"
    _make_mrc(tomo_dir / "recon.mrc", voxel_size_x=999.0)  # wildly wrong

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    assert result.errors == []
    # No mismatch — implied couldn't be computed.
    assert not any(
        w.category == "voxel_spacing_implied_mismatch" for w in result.warnings
    )
    assert not any(
        c.category == "voxel_spacing_implied_mismatch" for c in result.conflicts
    )
    aux_key = ("sample_sim", "Pos1", "tomo1")
    assert result.tomogram_aux[aux_key]["voxel_spacing_angstrom_implied"] is None
    assert result.tomogram_aux[aux_key]["voxel_spacing_angstrom"] == pytest.approx(
        999.0
    )


def test_unparseable_mdoc_emits_warning(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        """,
    )
    _write(
        sample_dir / "Pos1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"
        """,
    )
    _write(
        sample_dir / "Pos1" / "Frames" / "001.mdoc",
        """
        PixelSpacing = 2.93
        Voltage = not_a_number

        [ZValue = 0]
        TiltAngle = -60.0
        """,
    )

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    # An unreadable MDOC produces two `unparseable_mdoc` warnings with
    # distinct locations: one from the acquisition-level MDOC parser
    # (location ends in ``.Frames``) and one from the tilt-series parser
    # (location includes the MDOC path under ``.tilt_series[...]``).
    bad = [w for w in result.warnings if w.category == "unparseable_mdoc"]
    assert len(bad) == 2
    assert any(w.location.endswith("Pos1.Frames") for w in bad)
    assert any(".tilt_series[" in w.location for w in bad)

    acq = result.record.acquisitions["Pos1"].acquisition
    assert acq.pixel_size is None
    assert acq.voltage is None


def test_synthesized_frames_only_acquisition(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        """,
    )
    # No acquisition.toml under Pos1 — Frames-only
    _write(
        sample_dir / "Pos1" / "Frames" / "001.mdoc",
        """
        PixelSpacing = 2.93
        Voltage = 300

        [ZValue = 0]
        TiltAngle = -60.0
        ExposureDose = 0.5
        """,
    )
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    assert result.record is not None
    missing = [
        w for w in result.warnings if w.category == "missing_acquisition_toml"
    ]
    assert len(missing) == 1
    assert missing[0].location == "acquisitions.Pos1"

    acq = result.record.acquisitions["Pos1"].acquisition
    assert acq.acquisition_id == "Pos1"
    # MDOC still populates the synthesized acquisition
    assert acq.pixel_size == 2.93
    assert acq.voltage == 300.0
    assert acq.camera == "Falcon"  # .eer present


def test_unparseable_acquisition_toml_isolated(tmp_path):
    """Bad acquisition.toml -> isolated; good one validates fully."""
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        """,
    )
    # Good acquisition
    _write(
        sample_dir / "Good" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[tomogram]]
        id = "tomo_good"
        voxel_bin = 4
        """,
    )
    (sample_dir / "Good" / "Reconstructions" / "Tomograms" / "tomo_good").mkdir(parents=True)
    # Bad acquisition: target_tomogram references unknown tomogram
    _write(
        sample_dir / "Bad" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [[annotation]]
        id = "ann1"
        type = "membrane_segmentation"
        target_tomogram = "ghost"
        """,
    )

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    assert result.record is not None
    # Bad gets synthesized as a placeholder with an unparseable warning
    bad = [
        w
        for w in result.warnings
        if w.category == "unparseable_acquisition_toml"
    ]
    assert len(bad) == 1
    assert bad[0].location == "acquisitions.Bad"

    acqs = result.record.acquisitions
    assert "Good" in acqs
    assert "Bad" in acqs
    # Good is fully validated and contains its tomogram declaration
    assert [t.tomogram_id for t in acqs["Good"].tomogram] == ["tomo_good"]
    # Bad is a synthesized placeholder (empty)
    assert acqs["Bad"].tomogram == []
    assert acqs["Bad"].annotation == []


def test_typo_warning_categorized(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        descriptiom = "x"
        """,
    )
    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    typos = [w for w in result.warnings if w.category == "possible_typo"]
    assert len(typos) == 1
    # location captured from "on Sample closely matches"
    assert typos[0].location == "Sample"


def test_unfilled_placeholder_warning_categorized(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        description = "<FILL IN>"
        """,
    )
    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    placeholders = [
        w for w in result.warnings if w.category == "unfilled_placeholder"
    ]
    assert len(placeholders) == 1
    # Loader emits "<dotted.path>: unfilled <FILL IN> placeholder"
    # so location is the dotted path.
    assert "description" in placeholders[0].location


def test_undeclared_tomogram_folder_warns(tmp_path):
    """Folder under Reconstructions/Tomograms with no [[tomogram]] block warns."""
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        """,
    )
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"
        """,
    )
    # Folder exists on disk but is not declared in the TOML.
    (sample_dir / "acq1" / "Reconstructions" / "Tomograms" / "stray_tomo").mkdir(
        parents=True
    )

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    undeclared = [
        w for w in result.warnings if w.category == "undeclared_tomogram_folder"
    ]
    assert len(undeclared) == 1
    assert "stray_tomo" in undeclared[0].location
    assert "stray_tomo" in undeclared[0].message


def test_undeclared_annotation_folder_warns(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write(
        sample_dir / "sample.toml",
        """
        [sample]
        data_source = "cryoet"
        project = "chromatin"
        """,
    )
    _write(
        sample_dir / "acq1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"
        """,
    )
    (sample_dir / "acq1" / "Reconstructions" / "Annotations" / "stray_ann").mkdir(
        parents=True
    )

    loc = _sample_loc(sample_dir)
    result = assemble_sample(loc)

    undeclared = [
        w for w in result.warnings if w.category == "undeclared_annotation_folder"
    ]
    assert len(undeclared) == 1
    assert "stray_ann" in undeclared[0].location
    assert "stray_ann" in undeclared[0].message
