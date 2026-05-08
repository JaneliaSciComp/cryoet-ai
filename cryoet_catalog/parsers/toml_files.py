"""Thin delegate to ``cryoet_schema.loader.load_sample_record``.

The catalog scanner imports ``load_sample_toml`` through this module so that
callers do not need to know about ``cryoet_schema.loader`` directly. The
returned ``LoadResult`` exposes:

- ``record`` — validated ``SampleRecord`` (or ``None`` if unrecoverable);
- ``sample_errors`` / ``acquisition_errors`` — per-acquisition isolation;
- ``warnings`` — extra-field, possible-typo, unfilled-placeholder warnings;
- ``extras`` — structured extras for persistence.
"""
from __future__ import annotations

from pathlib import Path

from cryoet_schema.loader import LoadResult, load_sample_record


def load_sample_toml(sample_dir: Path) -> LoadResult:
    """Validate every TOML under ``sample_dir``.

    Returns the ``LoadResult`` from ``cryoet_schema.loader.load_sample_record``
    unchanged.
    """
    return load_sample_record(sample_dir)


__all__ = ["load_sample_toml", "LoadResult"]
