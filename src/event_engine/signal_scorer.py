"""Score event signals using configurable weights."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.utils.config_loader import load_yaml
from src.utils.time_utils import freshness_bucket


ROOT = Path(__file__).resolve().parents[2]


def score_event(event: Dict[str, Any], relevance: float) -> float:
    """Compute signed score from source, freshness, strength, relevance and confidence."""
    config = load_yaml(ROOT / "configs" / "scoring.yaml")
    src = config.get("source_weight", {}).get(event.get("source_level", "other"), 0.5)
    fresh = config.get("freshness_weight", {}).get(freshness_bucket(event.get("date", "")), 0.35)
    strength = config.get("event_strength_weight", {}).get("formal_announcement" if event.get("is_confirmed") else "rumor", 0.3)
    confidence = 0.8 if event.get("is_confirmed") else 0.4
    direction_sign = 0.0
    if event.get("short_term_direction") == "利好":
        direction_sign = 1.0
    elif event.get("short_term_direction") == "利空":
        direction_sign = -1.0
    return src * fresh * strength * relevance * direction_sign * confidence


def score_to_label(score: float) -> str:
    """Convert score into directional label."""
    if score >= 0.25:
        return "利好"
    if score <= -0.25:
        return "利空"
    return "中性"
