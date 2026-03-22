"""Fund profile loader for configs/funds.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.utils.config_loader import load_yaml


ROOT = Path(__file__).resolve().parents[2]


def load_fund_profiles() -> List[Dict[str, Any]]:
    """Load all configured fund profiles."""
    data = load_yaml(ROOT / "configs" / "funds.yaml")
    return data.get("funds", [])
