"""Configuration loader with optional PyYAML support and fallback parser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict


def _fallback_load_yaml(text: str) -> Dict[str, Any]:
    """Very small fallback parser for key-value/list YAML used in this repo.

    This parser only supports the simple YAML patterns used by the project
    and is intentionally limited. Prefer PyYAML when available.
    """
    data: Dict[str, Any] = {}
    current_key = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and not line.startswith("-"):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                data[key] = value.strip('"')
                current_key = None
            else:
                data[key] = []
                current_key = key
        elif line.startswith("-") and current_key:
            item = line.lstrip("-").strip().strip('"')
            if isinstance(data[current_key], list):
                data[current_key].append(item)
    return data


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML config file.

    Uses yaml.safe_load when PyYAML is available, otherwise falls back to a
    limited parser that supports this project's simple structures.
    """
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text)
        return parsed or {}
    except Exception:
        return _fallback_load_yaml(text)


def normalize_text(value: str) -> str:
    """Normalize text for keyword matching."""
    return re.sub(r"\s+", "", value.lower())
