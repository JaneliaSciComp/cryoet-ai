"""Integration tests: assembler pulls tilt-series records into SampleRecord."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cryoet_catalog.assembler import assemble_sample
from cryoet_catalog.discovery import SampleLocation


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(content).lstrip())


def _write_minimal_sample_toml(sample_dir: Path) -> Path:
    """Write the smallest legal sample.toml under ``sample_dir``.

    Centralised so a schema rev to ``[sample]`` only touches one place.
    """
    path = sample_dir / "sample.toml"
    _write(
        path,
        """
        [sample]
        data_source = "experimental"
        project = "chromatin"
        """,
    )
    return path


def _write_minimal_acquisition_toml(
    sample_dir: Path, acq_id: str = "Pos1", extra: str = ""
) -> Path:
    """Write the smallest legal acquisition.toml under ``sample_dir / acq_id``.

    ``extra`` is appended verbatim (after dedent/lstrip) for tests that need
    additional TOML blocks (e.g. ``[[post_processed_tomogram]]``).
    """
    path = sample_dir / acq_id / "acquisition.toml"
    body = """
        [acquisition]
        microscope = "Krios"
        """
    if extra:
        body = body + extra
    _write(path, body)
    return path


def _sample_loc(sample_dir: Path) -> SampleLocation:
    return SampleLocation(
        path=sample_dir,
        sample_id=sample_dir.name,
        sample_toml=sample_dir / "sample.toml",
    )


_MDOC = """\
PixelSpacing = 2.93
Voltage = 300
TiltAxisAngle = 84.5

[ZValue = 0]
TiltAngle = -60.0
ExposureDose = 0.5

[ZValue = 1]
TiltAngle = -57.0
ExposureDose = 0.5
"""


def test_assembler_merges_tilt_series_into_acquisition(tmp_path: Path) -> None:
    sample_dir = tmp_path / "sample_a"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)
    # Sibling tilt-image file so image_format gets detected.
    (sample_dir / "Pos1" / "Frames" / "001.eer").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    acq_file = result.record.acquisitions["Pos1"]
    assert len(acq_file.tilt_series) == 1

    ts = acq_file.tilt_series[0]
    assert ts.tilt_series_id == "ts"
    assert ts.n_tilts == 2
    assert ts.pixel_spacing == pytest.approx(2.93)
    assert ts.voltage == pytest.approx(300.0)
    assert ts.image_format == "EER"
    # microscope/camera from acquisition.toml only (plan §11.14) — leave None
    # on the tilt-series row even though acq has microscope='Krios'.
    assert ts.microscope is None
    assert ts.camera is None
    assert ts.tilt_angles == [pytest.approx(-60.0), pytest.approx(-57.0)]

    # Acquisition path recorded for the UI's copy-path / file-browser buttons.
    assert acq_file.acquisition.path == str(sample_dir / "Pos1")


def test_assembler_records_acquisition_path_for_synthesized(
    tmp_path: Path,
) -> None:
    """Synthesized acquisitions (no acquisition.toml) still get ``acq.path``."""
    sample_dir = tmp_path / "sample_b"
    _write_minimal_sample_toml(sample_dir)
    # No acquisition.toml; presence of Frames/ alone triggers discovery.
    (sample_dir / "Pos1" / "Frames").mkdir(parents=True)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    acq = result.record.acquisitions["Pos1"].acquisition
    assert acq.path == str(sample_dir / "Pos1")


def test_assembler_records_tomogram_size_bytes(tmp_path: Path) -> None:
    """``tomograms.size_bytes`` is recorded from the MRC file's on-disk size."""
    mrcfile_pkg = pytest.importorskip("mrcfile")
    np = pytest.importorskip("numpy")

    sample_dir = tmp_path / "sample_c"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(
        sample_dir,
        extra="""
        [[post_processed_tomogram]]
        id = "tomo_a"
        """,
    )
    mrc_path = (
        sample_dir / "Pos1" / "Reconstructions" / "Tomograms" / "tomo_a" / "vol.mrc"
    )
    mrc_path.parent.mkdir(parents=True)
    with mrcfile_pkg.new(str(mrc_path), overwrite=True) as m:
        m.set_data(np.zeros((4, 4, 4), dtype=np.float32))
        m.voxel_size = 1.0

    result = assemble_sample(_sample_loc(sample_dir))
    assert result.record is not None
    tomo = result.record.acquisitions["Pos1"].post_processed_tomogram[0]
    assert tomo.size_bytes is not None
    assert tomo.size_bytes == mrc_path.stat().st_size


_PER_TILT_HEADER = """\
PixelSpacing = 1.7
Voltage = 200
TiltAxisAngle = 92.5
"""


def test_per_tilt_layout_produces_one_row(tmp_path: Path) -> None:
    """Gouauxlab-style frames dir (3 per-tilt MDOCs + EERs) yields 1 row.

    Before Phase 4.6 each per-tilt MDOC produced its own spurious row.
    Now the parser collapses the group by common prefix.
    """
    sample_dir = tmp_path / "sample_gouaux"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    frames_dir = sample_dir / "Pos1" / "Frames"
    frames_dir.mkdir(parents=True)
    for idx, angle in enumerate(["-30.0", "0.0", "30.0"], start=1):
        (frames_dir / f"20241211_Hipp_42_{idx:03d}_{angle}.eer.mdoc").write_text(
            _PER_TILT_HEADER
        )
        (frames_dir / f"20241211_Hipp_42_{idx:03d}_{angle}.eer").write_bytes(b"")

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    acq_file = result.record.acquisitions["Pos1"]
    assert len(acq_file.tilt_series) == 1
    ts = acq_file.tilt_series[0]
    assert ts.tilt_series_id == "20241211_Hipp_42"
    assert ts.n_tilts == 3
    assert ts.tilt_angles == [
        pytest.approx(-30.0),
        pytest.approx(0.0),
        pytest.approx(30.0),
    ]
    # No layout_unknown warnings — all 3 MDOC names match the pattern.
    layout_warnings = [
        w for w in result.warnings if w.category == "tilt_series_layout_unknown"
    ]
    assert layout_warnings == []


def test_assembler_emits_layout_unknown_warning(tmp_path: Path) -> None:
    """A frames dir of non-series-level MDOCs whose names lack the angle
    pattern triggers a ``tilt_series_layout_unknown`` warning.
    """
    sample_dir = tmp_path / "sample_unknown"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    frames_dir = sample_dir / "Pos1" / "Frames"
    frames_dir.mkdir(parents=True)
    (frames_dir / "weird_name.mdoc").write_text(_PER_TILT_HEADER)
    (frames_dir / "another_weird.mdoc").write_text(_PER_TILT_HEADER)

    result = assemble_sample(_sample_loc(sample_dir))

    assert result.record is not None
    layout_warnings = [
        w for w in result.warnings if w.category == "tilt_series_layout_unknown"
    ]
    assert len(layout_warnings) == 1
    assert "Pos1" in layout_warnings[0].location


def test_assembler_emits_tilt_series_collision_warning(tmp_path: Path) -> None:
    """When two MDOCs in an acquisition would yield the same tilt_series_id,
    the assembler emits a tilt_series_id_collision warning.

    Real discovery scans direct children only, so stem collisions can't
    happen via filenames alone today. This test exercises the assembler
    path by calling the parser directly; the assembler wiring relays the
    parser's collisions list into ScanWarning entries.
    """
    from cryoet_catalog.parsers.tilt_series import (
        TiltSeriesCollision,
        TiltSeriesParseResult,
    )

    # Sanity check: TiltSeriesCollision instances flow through to warnings
    # via the assembler's loop. Build a minimal sample, monkey-patch the
    # parser, and assert the warning is emitted.
    import cryoet_catalog.assembler as assembler

    sample_dir = tmp_path / "sample_d"
    _write_minimal_sample_toml(sample_dir)
    _write_minimal_acquisition_toml(sample_dir)
    _write(sample_dir / "Pos1" / "Frames" / "ts.mdoc", _MDOC)

    fake_result = TiltSeriesParseResult(
        records=[],
        collisions=[
            TiltSeriesCollision(
                tilt_series_id="ts__Frames",
                original_stem="ts",
                mdoc_path=str(sample_dir / "Pos1" / "Frames" / "ts.mdoc"),
            )
        ],
        unreadable=[],
    )

    original = assembler.parse_tilt_series_dir
    assembler.parse_tilt_series_dir = lambda _path, **_kw: fake_result
    try:
        result = assemble_sample(_sample_loc(sample_dir))
    finally:
        assembler.parse_tilt_series_dir = original

    collisions = [
        w for w in result.warnings if w.category == "tilt_series_id_collision"
    ]
    assert len(collisions) == 1
    assert "ts__Frames" in collisions[0].location
