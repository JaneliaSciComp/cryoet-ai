"""Thin delegate to ``schema.loader.load_sample_record``.

The catalog scanner imports ``load_sample_toml`` through this module so that
callers do not need to know about ``schema.loader`` directly. The
returned ``LoadResult`` exposes:

- ``record`` — validated ``SampleRecord`` (or ``None`` if unrecoverable);
- ``sample_errors`` / ``acquisition_errors`` — per-acquisition isolation;
- ``warnings`` — extra-field, possible-typo, unfilled-placeholder warnings;
- ``extras`` — structured extras for persistence.
"""
from __future__ import annotations

from pathlib import Path

from schema.loader import LoadResult, load_sample_record
from schema.schema import DataSource, DatasetType


def load_sample_toml(
    sample_dir: Path,
    *,
    data_source: DataSource | None = None,
    dataset_type: DatasetType | None = None,
) -> LoadResult:
    """Validate every TOML under ``sample_dir``.

    ``data_source`` / ``dataset_type`` (the directory-derived arm) are threaded
    through to ``load_sample_record`` so the directory remains the source of
    truth. Returns the ``LoadResult`` unchanged.
    """
    return load_sample_record(
        sample_dir, data_source=data_source, dataset_type=dataset_type
    )


__all__ = ["load_sample_toml", "LoadResult"]
