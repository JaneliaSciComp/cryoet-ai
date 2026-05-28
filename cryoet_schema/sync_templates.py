"""Sync the starter-directory template copies from the canonical templates.

There are multiple on-disk copies of each researcher template:

- the standalone copies under ``templates/`` (canonical), and
- the starter-directory copies under ``templates/sample_name_experimental/``
  and ``templates/sample_name_simulation/`` that a researcher copies
  wholesale to begin a new sample. The two skeletons differ only in their
  empty-directory layout (experimental has ``Frames/``/``Gains/``/
  ``Alignments/``; simulation has ``md_runs/`` and no movie-frame folders) —
  the ``sample.toml`` / ``acquisition.toml`` contents are identical across
  both, so each canonical template fans out to both skeletons.

All copies must stay identical to their canonical source. This script
regenerates the starter copies from the canonical ones.
``tests/test_repo_consistency.py`` asserts they match, so a forgotten sync
fails the test suite.

Usage:
    pixi run sync-templates          # rewrite the starter copies
    python -m cryoet_schema.sync_templates --check   # exit 1 if out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# canonical (source) -> starter copy (generated). Keep these paths in sync
# with the directory layout documented in README.md. Each canonical template
# fans out to both the experimental and simulation starter skeletons.
_TEMPLATES = _REPO_ROOT / "templates"
_STARTER_SKELETONS = ("sample_name_experimental", "sample_name_simulation")

TEMPLATE_PAIRS: list[tuple[Path, Path]] = [
    pair
    for skeleton in _STARTER_SKELETONS
    for pair in (
        (
            _TEMPLATES / "sample.toml",
            _TEMPLATES / skeleton / "sample.toml",
        ),
        (
            _TEMPLATES / "acquisition.toml",
            _TEMPLATES / skeleton / "acquisition_name" / "acquisition.toml",
        ),
    )
]


def _out_of_sync() -> list[tuple[Path, Path]]:
    """Return (canonical, copy) pairs whose copy differs from the canonical."""
    stale: list[tuple[Path, Path]] = []
    for canonical, copy in TEMPLATE_PAIRS:
        canonical_text = canonical.read_text()
        if not copy.is_file() or copy.read_text() != canonical_text:
            stale.append((canonical, copy))
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any starter copy is out of date; write nothing",
    )
    args = parser.parse_args(argv)

    stale = _out_of_sync()

    if args.check:
        if stale:
            for _canonical, copy in stale:
                print(f"out of date: {copy.relative_to(_REPO_ROOT)}")
            print("run `pixi run sync-templates` to regenerate")
            return 1
        print("starter templates are in sync")
        return 0

    for canonical, copy in stale:
        copy.write_text(canonical.read_text())
        print(f"wrote {copy.relative_to(_REPO_ROOT)}")
    if not stale:
        print("starter templates already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
