"""Simple JSON file cache utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_json(path: Path, data: Any) -> None:
    """Save JSON with UTF-8 and indentation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
