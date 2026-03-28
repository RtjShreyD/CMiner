"""Generic filesystem helpers for all agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    """Create directory recursively if missing and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text(path: Path, content: str) -> Path:
    """Write UTF-8 text to file and return path."""

    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def append_text(path: Path, content: str) -> Path:
    """Append UTF-8 text to file and return path."""

    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)
    return path


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write JSON payload to file and return path."""

    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
