"""Tests for cryoet_catalog.assembler."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import mrcfile
import numpy as np
import pytest

from cryoet_catalog.assembler import (
    AssemblyResult,
    ScanWarning,
    assemble_sample,
)
from cryoet_catalog.discovery import SampleLocation, iter_samples

FIXTURES = Path(__file__).parent / "fixtures"


# ── helpers ──────────────────────────────────────────────────────────────────


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(content).lstrip())


def _write_minimal_sample_toml(sample_dir: Path, extra: str = "") -> Path:
    """Write the smallest legal sample.toml under ``sample_dir``.

    ``extra`` is appended verbatim inside the ``[sample]`` block for tests
    that need an additional field (e.g. ``description = "<FILL IN>"`` or
    a deliberate typo). Centralised so a schema rev to ``[sample]`` only
    touches one place.
    """
    path = sample_dir / "sample.toml"
    body = """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """
    if extra:
        body = body + "        " + extra.strip() + "\n"
    _write(path, body)
    return path


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

    # Raw tomogram populated from MRC + zarr parsers
    raw = acqs["Position_86"].raw_tomogram
    assert raw is not None
    assert raw.tomogram_id == "bp_3dctf_bin4"
    assert raw.image_size_x == 4
    assert raw.mrc_path is not None
    assert raw.zarr_path is not None
    assert raw.zarr_axes == "zyx"
    assert raw.zarr_scale == [11.72, 11.72, 11.72]

    # Annotation files populated
    anns = {a.annotation_id: a for a in acqs["Position_86"].annotation}
    assert "membrain_seg_v10" in anns
    files = anns["membrain_seg_v10"].files
    assert files, "annotation files should be populated from disk"
    assert any(f.endswith("segmentation.mrc") for f in files)
    assert any(f.endswith("metadata.json") for f in files)
    assert files == sorted(files)


def _build_basic_experimental_sample(
    sample_dir: Path,
    *,
    pixel_size: float = 2.93,
    voltage: float = 300.0,
    extra_sample_block: str = "",
) -> SampleLocation:
    _write(
        sample_dir / "sample.toml",
        f"""
        [sample]
        data_source = "experimental"
        project = "chromatin"
        description = "test"
        {extra_sample_block}
        """,
    )
    _write(
        sample_dir / "Pos1" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [raw_tomogram]
        id = "tomo1"
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
    _make_mrc(tomo_dir / "recon.mrc")
    _make_zattrs(tomo_dir / "recon.ome.zarr")
    return _sample_loc(sample_dir)


def test_unparseable_mdoc_emits_warning(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
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
    _write_minimal_sample_toml(sample_dir)
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
    _write_minimal_sample_toml(sample_dir)
    # Good acquisition
    _write(
        sample_dir / "Good" / "acquisition.toml",
        """
        [acquisition]
        microscope = "Krios"

        [raw_tomogram]
        id = "tomo_good"
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
    # Good is fully validated and contains its raw tomogram declaration.
    good_raw = acqs["Good"].raw_tomogram
    assert good_raw is not None and good_raw.tomogram_id == "tomo_good"
    assert acqs["Good"].post_processed_tomogram == []
    # Bad is a synthesized placeholder (empty)
    assert acqs["Bad"].raw_tomogram is None
    assert acqs["Bad"].post_processed_tomogram == []
    assert acqs["Bad"].annotation == []


def test_typo_warning_categorized(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir, extra='descriptiom = "x"')
    loc = _sample_loc(sample_dir)
    # The underlying Pydantic typo-detector emits a UserWarning; the assembler
    # then re-emits it as a categorized ScanWarning. We assert the UserWarning
    # is raised (and capture it) so it doesn't leak into the test summary.
    with pytest.warns(UserWarning, match="closely matches"):
        result = assemble_sample(loc)

    typos = [w for w in result.warnings if w.category == "possible_typo"]
    assert len(typos) == 1
    # location captured from "on Sample closely matches"
    assert typos[0].location == "Sample"


def test_unfilled_placeholder_warning_categorized(tmp_path):
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir, extra='description = "<FILL IN>"')
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
    """Folder under Reconstructions/Tomograms with no tomogram block warns."""
    sample_dir = tmp_path / "sample_test"
    _write_minimal_sample_toml(sample_dir)
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
    _write_minimal_sample_toml(sample_dir)
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
