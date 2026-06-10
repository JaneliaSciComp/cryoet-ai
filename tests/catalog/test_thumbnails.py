"""Tests for catalog.thumbnails."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from catalog.thumbnails import (
    THUMBNAIL_WIDTH,
    TomoRef,
    _relpath,
    _safe_segment,
    generate_thumbnails,
    representative_relpath,
)

# Minimal PNG header used as fake output from _render_one.
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


# ── _safe_segment ─────────────────────────────────────────────────────────────


def test_safe_segment_valid():
    assert _safe_segment("sample_chromatin") == "sample_chromatin"
    assert _safe_segment("Position_86") == "Position_86"
    assert _safe_segment("bp_3dctf_bin4") == "bp_3dctf_bin4"


def test_safe_segment_rejects_traversal():
    with pytest.raises(ValueError):
        _safe_segment("..")
    with pytest.raises(ValueError):
        _safe_segment("a/b")
    with pytest.raises(ValueError):
        _safe_segment("")


# ── _relpath ─────────────────────────────────────────────────────────────────


def test_relpath_structure():
    assert _relpath("s", "a", "t") == "s/a/t.png"


# ── generate_thumbnails ───────────────────────────────────────────────────────


def _fake_render_one(mrc_path: str, dest: Path) -> bool:
    """Side effect for patching _render_one: writes fake PNG and returns True."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_FAKE_PNG)
    return True


def test_generate_thumbnails_writes_png_and_returns_relpath(tmp_path):
    ref = TomoRef(
        acquisition_id="acq1",
        kind="post",
        tomogram_id="t1",
        mrc_path="/data/t1.mrc",
    )
    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        result = generate_thumbnails("sample_a", [ref], tmp_path)

    expected_rel = "sample_a/acq1/t1.png"
    assert result == expected_rel
    out_file = tmp_path / expected_rel
    assert out_file.is_file()
    assert out_file.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_thumbnails_zarr_only_skipped(tmp_path):
    ref = TomoRef(
        acquisition_id="acq1",
        kind="post",
        tomogram_id="t1",
        mrc_path=None,  # Zarr-only, no MRC
    )
    with patch("catalog.thumbnails._render_one") as mock_render:
        result = generate_thumbnails("sample_a", [ref], tmp_path)

    mock_render.assert_not_called()
    assert result is None


def test_generate_thumbnails_skip_existing_does_not_re_render(tmp_path):
    ref = TomoRef(
        acquisition_id="acq1",
        kind="post",
        tomogram_id="t1",
        mrc_path="/data/t1.mrc",
    )
    expected_rel = "sample_a/acq1/t1.png"
    dest = tmp_path / expected_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_FAKE_PNG)
    original_mtime = dest.stat().st_mtime

    with patch("catalog.thumbnails._render_one") as mock_render:
        result = generate_thumbnails("sample_a", [ref], tmp_path, skip_existing=True)

    mock_render.assert_not_called()
    assert result == expected_rel
    assert dest.stat().st_mtime == original_mtime


def test_generate_thumbnails_skip_existing_renders_missing(tmp_path):
    ref = TomoRef(
        acquisition_id="acq1",
        kind="post",
        tomogram_id="t1",
        mrc_path="/data/t1.mrc",
    )
    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one) as mock_render:
        result = generate_thumbnails("sample_a", [ref], tmp_path, skip_existing=True)

    mock_render.assert_called_once()
    assert result == "sample_a/acq1/t1.png"


def test_generate_thumbnails_overwrites_no_tmp_left_behind(tmp_path):
    ref = TomoRef(
        acquisition_id="acq1",
        kind="post",
        tomogram_id="t1",
        mrc_path="/data/t1.mrc",
    )
    with patch("catalog.thumbnails._render_one", side_effect=_fake_render_one):
        generate_thumbnails("sample_a", [ref], tmp_path)

    # No .png.tmp files should be left behind
    tmp_files = list(tmp_path.rglob("*.png.tmp"))
    assert tmp_files == []


# ── representative_relpath ────────────────────────────────────────────────────


def test_representative_relpath_post_beats_raw():
    generated = {
        ("acq1", "post"): "s/acq1/t_post.png",
        ("acq1", "raw"): "s/acq1/t_raw.png",
    }
    assert representative_relpath(generated) == "s/acq1/t_post.png"


def test_representative_relpath_raw_fallback():
    generated = {
        ("acq1", "raw"): "s/acq1/t_raw.png",
    }
    assert representative_relpath(generated) == "s/acq1/t_raw.png"


def test_representative_relpath_falls_through_to_later_acq():
    # acq1 has no entry, acq2 has raw
    generated = {
        ("acq2", "raw"): "s/acq2/t_raw.png",
    }
    assert representative_relpath(generated) == "s/acq2/t_raw.png"


def test_representative_relpath_first_acq_wins_when_both_present():
    # Sorted by acquisition_id → acq1 comes before acq2
    generated = {
        ("acq1", "raw"): "s/acq1/t_raw.png",
        ("acq2", "raw"): "s/acq2/t_raw.png",
    }
    assert representative_relpath(generated) == "s/acq1/t_raw.png"


def test_representative_relpath_empty_dict():
    assert representative_relpath({}) is None
