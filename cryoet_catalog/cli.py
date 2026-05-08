"""Command-line entry point for the catalog scanner.

Usage::

    python -m cryoet_catalog scan <root>
        [--db sqlite:///path.db] [--force] [--init]
        [--prune] [--prune-dry-run] [--prune-safety-floor 0.5]
        [--on-voxel-mismatch warn|error]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryoet_catalog import db, scanner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m cryoet_catalog")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan", help="Scan a data root and ingest into the catalog DB."
    )
    scan.add_argument("root", type=Path, help="path to data root")
    scan.add_argument(
        "--db", default=db.DEFAULT_DB_URL, help="SQLAlchemy URL"
    )
    scan.add_argument(
        "--force", action="store_true", help="bypass mtime gating"
    )
    scan.add_argument(
        "--init", action="store_true", help="create tables on a fresh DB"
    )
    scan.add_argument(
        "--prune",
        action="store_true",
        help="soft-delete samples missing from disk",
    )
    scan.add_argument(
        "--prune-dry-run",
        action="store_true",
        help="report would-be soft-deletes without writing",
    )
    scan.add_argument(
        "--prune-safety-floor",
        type=float,
        default=0.5,
        help=(
            "abort prune if fraction of live samples to delete exceeds this "
            "(default 0.5)"
        ),
    )
    scan.add_argument(
        "--on-voxel-mismatch",
        choices=["warn", "error"],
        default="warn",
        help="how to handle voxel-spacing implied vs MRC mismatches",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return _cmd_scan(args)
    return 2


def _cmd_scan(args) -> int:
    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    engine = db.make_engine(args.db)
    if args.init:
        db.init_schema(engine)

    try:
        report = scanner.scan_root(
            engine,
            args.root.resolve(),
            force=args.force,
            prune=args.prune,
            prune_dry_run=args.prune_dry_run,
            prune_safety_floor=args.prune_safety_floor,
            on_voxel_mismatch=args.on_voxel_mismatch,
        )
    except Exception as e:  # noqa: BLE001
        print(f"scan failed: {e}", file=sys.stderr)
        return 1

    print(f"upserted: {report.upserted}")
    print(f"skipped:  {report.skipped}")
    print(f"warnings: {len(report.warnings)}")
    print(f"errors:   {len(report.errors)}")
    if report.conflicts:
        print(f"conflicts: {len(report.conflicts)}")
    if report.would_soft_delete is not None:
        print(f"would soft-delete: {report.would_soft_delete}")
    elif report.soft_deleted:
        print(f"soft-deleted: {report.soft_deleted}")

    if report.errors:
        for e in report.errors[:10]:
            print(f"  error: {e}", file=sys.stderr)
        if len(report.errors) > 10:
            print(f"  (+ {len(report.errors) - 10} more)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
