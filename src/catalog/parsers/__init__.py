"""Pure-function parsers. Each takes a Path and returns either a dict[str, Any]
of fields (toml_files) or a ParseResult (the four supplementary parsers)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ParseResult:
    fields: dict[str, Any] = field(default_factory=dict)
    status: Literal["ok", "missing", "unreadable"] = "ok"
    error: str | None = None
