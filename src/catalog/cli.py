"""Command-line entry point for the catalog scanner.

Usage::

    python -m catalog scan <root>
        [--db sqlite:///path.db] [--force] [--init]
        [--prune] [--prune-dry-run] [--prune-safety-floor 0.5]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from catalog import db, scanner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m catalog")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan", help="Scan a data root and ingest into the catalog DB."
    )
    scan.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=None,
        help="path to data root (defaults to $CATALOG_DATA_ROOT)",
    )
    scan.add_argument(
        "--db",
        default=os.environ.get("CATALOG_DB_URL", db.DEFAULT_DB_URL),
        help="SQLAlchemy URL (defaults to $CATALOG_DB_URL, else sqlite:///catalog.db)",
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
        "--thumbnail-dir",
        default=os.environ.get("CATALOG_THUMBNAIL_DIR"),
        help="directory for pre-generated thumbnail cache (defaults to $CATALOG_THUMBNAIL_DIR)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return _cmd_scan(args)
    return 2


def _cmd_scan(args) -> int:
    root = args.root
    if root is None:
        env_root = os.environ.get("CATALOG_DATA_ROOT")
        if not env_root:
            print(
                "error: no root provided and CATALOG_DATA_ROOT is not set",
                file=sys.stderr,
            )
            return 2
        root = Path(env_root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    args.root = root

    engine = db.make_engine(args.db)
    if args.init:
        db.init_schema(engine)

    thumbnail_dir = None
    if args.thumbnail_dir:
        thumbnail_dir = Path(args.thumbnail_dir)
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = scanner.scan_root(
            engine,
            args.root.resolve(),
            force=args.force,
            prune=args.prune,
            prune_dry_run=args.prune_dry_run,
            prune_safety_floor=args.prune_safety_floor,
            thumbnail_dir=thumbnail_dir,
        )
    except Exception as e:  # noqa: BLE001
        print(f"scan failed: {e}", file=sys.stderr)
        return 1

    print(f"upserted: {report.upserted}")
    print(f"skipped:  {report.skipped}")
    if report.thumbnails_healed:
        print(f"thumbnails_healed: {report.thumbnails_healed}")
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
