"""Unit tests for the path-walking discovery layer."""

from __future__ import annotations

from pathlib import Path

from cryoet_catalog.discovery import (
    iter_acquisitions,
    iter_annotations,
    iter_samples,
    iter_tomograms,
    parse_targets_for_sample,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_iter_samples_finds_chromatin_and_simulation():
    samples = sorted(iter_samples(FIXTURES), key=lambda s: s.sample_id)
    assert [s.sample_id for s in samples] == [
        "sample_chromatin",
        "sample_simulation",
    ]
    chrom = samples[0]
    assert chrom.sample_toml.exists()
    assert chrom.path.is_dir()


def test_iter_samples_skips_dirs_without_sample_toml(tmp_path):
    (tmp_path / "no_toml_here").mkdir()
    (tmp_path / "with_toml").mkdir(exist_ok=True)
    (tmp_path / "with_toml" / "sample.toml").write_text(
        "[sample]\ndata_source='cryoet'\nproject='chromatin'\n"
    )
    found = list(iter_samples(tmp_path))
    assert {s.sample_id for s in found} == {"with_toml"}


def test_iter_acquisitions_finds_toml_and_frames_only():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    acqs = sorted(iter_acquisitions(sample), key=lambda a: a.acquisition_id)
    assert [a.acquisition_id for a in acqs] == ["Position_86", "Position_87"]
    pos86, pos87 = acqs
    assert pos86.acquisition_toml is not None and pos86.acquisition_toml.is_file()
    assert pos87.acquisition_toml is None  # Frames-only acquisition
    assert pos86.frames_dir is not None
    assert pos86.tomograms_dir is not None
    assert pos86.annotations_dir is not None


def test_iter_tomograms_lists_pipeline_folders():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    pos86 = next(
        a for a in iter_acquisitions(sample) if a.acquisition_id == "Position_86"
    )
    tomos = list(iter_tomograms(pos86))
    assert len(tomos) == 1
    assert tomos[0].tomogram_id == "bp_3dctf_bin4"
    assert any(p.suffix == ".mrc" for p in tomos[0].mrc_files)
    assert any(p.name.endswith(".ome.zarr") for p in tomos[0].zarr_dirs)


def test_iter_annotations_filters_by_extension():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    pos86 = next(
        a for a in iter_acquisitions(sample) if a.acquisition_id == "Position_86"
    )
    anns = list(iter_annotations(pos86))
    assert len(anns) == 1
    ann = anns[0]
    assert ann.annotation_id == "membrain_seg_v10"
    file_names = {p.name for p in ann.files}
    assert "segmentation.mrc" in file_names
    assert "metadata.json" in file_names
    assert ".DS_Store" not in file_names


def test_parse_targets_for_sample_includes_all_categories():
    sample = next(
        s for s in iter_samples(FIXTURES) if s.sample_id == "sample_chromatin"
    )
    targets = parse_targets_for_sample(sample)
    target_strs = {str(t) for t in targets}
    # sample.toml present
    assert any(t.endswith("sample.toml") for t in target_strs)
    # acquisition.toml only for Position_86 (Position_87 has none)
    assert sum(1 for t in target_strs if t.endswith("acquisition.toml")) == 1
    # mdoc present
    assert any(t.endswith(".mdoc") for t in target_strs)
    # mrc inside Tomograms
    assert any(t.endswith("recon.mrc") for t in target_strs)
    # zarr .zattrs
    assert any(t.endswith(".zattrs") for t in target_strs)
    # representative frame file (.eer for Position_86 and Position_87)
    eer_count = sum(1 for t in target_strs if t.endswith(".eer"))
    assert eer_count >= 1  # at least one rep frame per acquisition with a Frames/ dir
    # deterministic, unique
    assert sorted(targets, key=lambda p: str(p)) == targets
    assert len(set(targets)) == len(targets)
