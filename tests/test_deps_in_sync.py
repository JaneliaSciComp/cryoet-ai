"""Guard against [project.dependencies] and [tool.pixi.dependencies] drifting.

We keep both lists in pyproject.toml — PEP 621 deps for pip/uv users, pixi
deps so pixi resolves the same packages from conda-forge. This test fails if
they fall out of sync.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# Packages tracked only by pixi (not pip-installable), excluded from the diff.
PIXI_ONLY: set[str] = {"python"}

# Add entries here only if a package's conda-forge name differs from its
# PyPI name. Both current deps (pydantic, rapidfuzz) match on both sides.
CONDA_TO_PYPI: dict[str, str] = {}


def _split_spec(spec: str) -> tuple[str, str]:
    """'pydantic>=2.6' -> ('pydantic', '>=2.6'). Bare names return ('name', '')."""
    for op in (">=", "<=", "==", "~=", ">", "<"):
        if op in spec:
            name, _, ver = spec.partition(op)
            return name.strip(), op + ver.strip()
    return spec.strip(), ""


def _normalize_conda(table: dict) -> dict[str, str]:
    """Convert a [tool.pixi.*dependencies] table to {pypi_name: version_spec}."""
    out: dict[str, str] = {}
    for name, spec in table.items():
        if name in PIXI_ONLY:
            continue
        version = spec if isinstance(spec, str) else spec.get("version", "")
        out[CONDA_TO_PYPI.get(name, name)] = version
    return out


def _normalize_pypi(specs: list[str]) -> dict[str, str]:
    return dict(_split_spec(s) for s in specs)


def test_runtime_deps_in_sync():
    data = tomllib.loads(PYPROJECT.read_text())
    conda = _normalize_conda(data["tool"]["pixi"]["dependencies"])
    pypi = _normalize_pypi(data["project"]["dependencies"])
    assert conda == pypi, (
        "Runtime deps in [tool.pixi.dependencies] and [project.dependencies] "
        f"have drifted.\n  pixi (conda): {conda}\n  project (pypi): {pypi}"
    )


def test_test_feature_deps_in_sync():
    data = tomllib.loads(PYPROJECT.read_text())
    conda = _normalize_conda(data["tool"]["pixi"]["feature"]["test"]["dependencies"])
    pypi = _normalize_pypi(data["project"]["optional-dependencies"]["test"])
    assert conda == pypi, (
        "Test deps in [tool.pixi.feature.test.dependencies] and "
        "[project.optional-dependencies.test] have drifted.\n"
        f"  pixi (conda): {conda}\n  project (pypi): {pypi}"
    )
