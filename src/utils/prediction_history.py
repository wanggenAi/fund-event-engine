"""Persist prediction snapshots for realized-outcome evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.pipeline.contracts import FundReport
from src.utils.cache import save_json


ROOT = Path(__file__).resolve().parents[2]


def default_prediction_history_path() -> Path:
    """Default location for prediction snapshots."""
    return ROOT / "outputs" / "history" / "fund_prediction_history.json"


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def append_prediction_snapshots(
    reports: Iterable[FundReport],
    analysis_window_days: int,
    prediction_history_path: str | None = None,
) -> Dict[str, Any]:
    """Append current run predictions for later realized-outcome evaluation."""
    path = Path(prediction_history_path) if prediction_history_path else default_prediction_history_path()
    rows = _load_rows(path)
    now = datetime.now(timezone.utc)
    asof_date = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    added = 0
    for r in reports:
        key_event_sources = [str(e.get("source", "")).strip() for e in r.key_events if str(e.get("source", "")).strip()]
        key_event_sources = list(dict.fromkeys(key_event_sources))
        rows.append(
            {
                "timestamp": ts,
                "asof_date": asof_date,
                "analysis_window_days": int(analysis_window_days),
                "fund_code": r.fund_code,
                "fund_name": r.fund_name,
                "fund_type": r.fund_type,
                "direction_3d": r.direction_3d,
                "direction_2w": r.direction_2w,
                "direction_3m": r.direction_3m,
                "long_term_logic": r.long_term_logic,
                "confidence": float(r.confidence),
                "conclusion_strength": r.conclusion_strength,
                "reference_value_score": float(r.reference_value_score),
                "recent_event_count": int(r.recent_event_count),
                "key_event_sources": key_event_sources,
            }
        )
        added += 1
    save_json(path, rows)
    return {"prediction_history_path": str(path), "prediction_snapshots_added": added}
