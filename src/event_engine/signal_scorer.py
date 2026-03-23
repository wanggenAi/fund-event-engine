"""Score event signals using configurable weights and gating bands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.utils.config_loader import load_yaml
from src.utils.time_utils import freshness_bucket


ROOT = Path(__file__).resolve().parents[2]


def _config() -> Dict[str, Any]:
    return load_yaml(ROOT / "configs" / "scoring.yaml")


def score_event(event: Dict[str, Any], relevance: float, horizon: str = "2w") -> float:
    """Compute signed score from source, freshness, strength, relevance and confidence."""
    config = _config()

    source_level = event.get("source_level", "other")
    src = config.get("source_weight", {}).get(source_level, 0.45)

    fresh_bucket = freshness_bucket(event.get("date", ""))
    fresh = config.get("freshness_weight", {}).get(fresh_bucket, 0.3)

    strength_key = event.get("event_strength_key", "confirmed_report")
    strength = event.get("event_strength")
    if strength is None:
        strength = config.get("event_strength_weight", {}).get(strength_key, 0.55)

    confidence = max(0.0, min(1.0, float(event.get("confidence", 0.8 if event.get("is_confirmed") else 0.4))))

    direction_sign = 0.0
    if event.get("short_term_direction") == "利好":
        direction_sign = 1.0
    elif event.get("short_term_direction") == "利空":
        direction_sign = -1.0

    base_score = src * fresh * float(strength) * relevance * direction_sign * confidence

    horizon_adj = config.get("horizon_adjustments", {}).get(horizon, {})
    base_score *= float(horizon_adj.get("freshness_multiplier", 1.0))

    return round(base_score, 6)


def score_to_label(score: float) -> str:
    """Convert score into directional label using configurable score bands."""
    bands = _config().get("final_score_bands", {})
    strong_bull = float(bands.get("strong_bullish", 0.65))
    bull = float(bands.get("bullish", 0.25))
    bear = float(bands.get("bearish", -0.25))
    strong_bear = float(bands.get("strong_bearish", -0.65))

    if score >= strong_bull:
        return "利好"
    if score >= bull:
        return "利好"
    if score <= strong_bear:
        return "利空"
    if score <= bear:
        return "利空"
    return "中性"
