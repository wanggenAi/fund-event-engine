"""Map raw text to normalized taxonomy types/subtypes."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from src.utils.config_loader import load_yaml, normalize_text


ROOT = Path(__file__).resolve().parents[2]


def map_taxonomy(text: str) -> Tuple[str, str]:
    """Return (event_type, event_subtype) using alias matching."""
    taxonomy = load_yaml(ROOT / "configs" / "taxonomy.yaml")
    normalized = normalize_text(text)
    tree = taxonomy.get("event_taxonomy", {})
    for event_type, info in tree.items():
        for subtype in info.get("subtypes", []):
            aliases = subtype.get("aliases", [])
            if any(normalize_text(str(a)) in normalized for a in aliases):
                return event_type, subtype.get("key", "unknown")
    return "sentiment", "commentary"
