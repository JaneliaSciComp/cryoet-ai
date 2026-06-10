"""CLI wrapper around ``schema.loader.load_sample_record``.

Usage:
    pixi run validate <sample_dir>
    python -m schema.validate <sample_dir>

Loads ``<sample_dir>/sample.toml`` plus every ``*/acquisition.toml`` one
level below, validates per §4.4.1's per-acquisition isolation rules,
prints warnings (typo suggestions, extra-field hints, unfilled
placeholders) and errors with JSON-path-like locators, and returns an
exit code (0 ok, 1 validation failure, 2 usage error).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from schema.loader import load_sample_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a cryoET sample directory against the Pydantic schema."
    )
    parser.add_argument(
        "sample_dir",
        type=Path,
        help="path to the sample directory (containing sample.toml)",
    )
    args = parser.parse_args(argv)

    sample_dir = args.sample_dir
    if not sample_dir.is_dir():
        print(f"error: {sample_dir} is not a directory", file=sys.stderr)
        return 2

    result = load_sample_record(sample_dir.resolve())

    for w in result.warnings:
        print(f"warning: {w}")
    for e in result.sample_errors:
        print(f"error: {e}", file=sys.stderr)
    for acq_id, msg in result.acquisition_errors.items():
        print(f"error: acquisitions.{acq_id}: {msg}", file=sys.stderr)

    if result.sample_errors or result.acquisition_errors:
        n_err = len(result.sample_errors) + len(result.acquisition_errors)
        print(
            f"\nFAIL: {n_err} error(s), {len(result.warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1

    n_acq = len(result.record.acquisitions) if result.record else 0
    print(
        f"\nOK: sample '{sample_dir.name}' validated "
        f"({n_acq} acquisition(s), {len(result.warnings)} warning(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
