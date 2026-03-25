"""Build source-performance feedback for runtime scoring adjustment."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Tuple


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_ymd(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _decay_weight(asof_date: str, now: datetime, half_life_days: int, decay_floor: float) -> float:
    dt = _parse_ymd(asof_date)
    if not dt:
        return 1.0
    age_days = max(0, (now - dt).days)
    if half_life_days <= 0:
        return 1.0
    # exponential decay: each half-life halves incremental weight, then clipped by floor.
    raw = 0.5 ** (age_days / float(half_life_days))
    return _clamp(raw, decay_floor, 1.0)


def _dynamic_threshold(
    base_min_samples: int,
    floor_min_samples: int,
    available_rows: int,
    enable_dynamic: bool,
) -> float:
    floor_eff = min(max(1, int(floor_min_samples)), max(1, int(base_min_samples)))
    if not enable_dynamic:
        return float(base_min_samples)
    if available_rows < base_min_samples * 3:
        return float(max(floor_eff, base_min_samples - 2))
    if available_rows < base_min_samples * 6:
        return float(max(floor_eff, base_min_samples - 1))
    return float(base_min_samples)


def build_source_feedback(
    prediction_rows: Iterable[Dict[str, object]],
    eval_details: Iterable[Dict[str, object]],
    min_samples: int = 6,
    sensitivity: float = 0.5,
    min_multiplier: float = 0.85,
    max_multiplier: float = 1.15,
    half_life_days: int = 45,
    decay_floor: float = 0.35,
    enable_dynamic_min_samples: bool = True,
    min_samples_floor: int = 2,
    enable_uncertainty_shrinkage: bool = True,
    shrinkage_strength: float = 6.0,
) -> Dict[str, object]:
    """Build per-source realized hit-rate and recommended score multipliers."""
    prediction_rows = list(prediction_rows)
    eval_details = list(eval_details)

    sources_by_key: Dict[Tuple[str, str], List[str]] = {}
    for row in prediction_rows:
        key = (str(row.get("fund_code", "")), str(row.get("asof_date", "")))
        srcs = row.get("key_event_sources", [])
        if not isinstance(srcs, list):
            continue
        cleaned = list(dict.fromkeys([str(x).strip() for x in srcs if str(x).strip()]))
        if cleaned:
            sources_by_key[key] = cleaned

    fund_type_by_key: Dict[Tuple[str, str], str] = {}
    for row in prediction_rows:
        key = (str(row.get("fund_code", "")), str(row.get("asof_date", "")))
        fund_type_by_key[key] = str(row.get("fund_type", "") or "unknown")

    now = datetime.now(timezone.utc)
    stats = defaultdict(lambda: {"total_weight": 0.0, "matched_weight": 0.0, "rows": 0})
    stats_by_fund_type = defaultdict(lambda: defaultdict(lambda: {"total_weight": 0.0, "matched_weight": 0.0, "rows": 0}))
    stats_by_horizon = defaultdict(lambda: defaultdict(lambda: {"total_weight": 0.0, "matched_weight": 0.0, "rows": 0}))
    stats_by_fund_type_horizon = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: {"total_weight": 0.0, "matched_weight": 0.0, "rows": 0}))
    )
    eval_rows_ok = 0
    for d in eval_details:
        if str(d.get("status", "")) != "ok":
            continue
        eval_rows_ok += 1
        key = (str(d.get("fund_code", "")), str(d.get("asof_date", "")))
        srcs = sources_by_key.get(key, [])
        if not srcs:
            continue
        matched = bool(d.get("matched", False))
        hz = str(d.get("horizon", "") or "unknown")
        w = _decay_weight(str(d.get("asof_date", "")), now=now, half_life_days=half_life_days, decay_floor=decay_floor)
        for s in srcs:
            stats[s]["total_weight"] += w
            stats[s]["rows"] += 1
            if matched:
                stats[s]["matched_weight"] += w
            ft = fund_type_by_key.get(key, "unknown")
            stats_by_fund_type[ft][s]["total_weight"] += w
            stats_by_fund_type[ft][s]["rows"] += 1
            if matched:
                stats_by_fund_type[ft][s]["matched_weight"] += w
            stats_by_horizon[hz][s]["total_weight"] += w
            stats_by_horizon[hz][s]["rows"] += 1
            if matched:
                stats_by_horizon[hz][s]["matched_weight"] += w
            stats_by_fund_type_horizon[ft][hz][s]["total_weight"] += w
            stats_by_fund_type_horizon[ft][hz][s]["rows"] += 1
            if matched:
                stats_by_fund_type_horizon[ft][hz][s]["matched_weight"] += w

    rows: List[Dict[str, object]] = []
    multipliers: Dict[str, float] = {}
    global_threshold = _dynamic_threshold(
        base_min_samples=int(min_samples),
        floor_min_samples=int(min_samples_floor),
        available_rows=int(eval_rows_ok),
        enable_dynamic=bool(enable_dynamic_min_samples),
    )
    for source, v in sorted(stats.items(), key=lambda kv: kv[1]["total_weight"], reverse=True):
        total_w = float(v["total_weight"])
        matched_w = float(v["matched_weight"])
        rows_count = int(v["rows"])
        acc_raw = (matched_w / total_w) if total_w > 0 else 0.0
        if enable_uncertainty_shrinkage and total_w > 0:
            # Bayesian-style shrinkage toward neutral 0.5 under small effective samples.
            acc = (matched_w + 0.5 * shrinkage_strength) / (total_w + shrinkage_strength)
        else:
            acc = acc_raw
        eligible = total_w >= global_threshold
        if eligible:
            raw = 1.0 + (acc - 0.5) * sensitivity
            rec = round(_clamp(raw, min_multiplier, max_multiplier), 4)
            multipliers[source] = rec
        else:
            rec = 1.0
        rows.append(
            {
                "source": source,
                "rows": rows_count,
                "effective_samples": round(total_w, 4),
                "effective_matched": round(matched_w, 4),
                "accuracy_raw": round(acc_raw, 4),
                "accuracy_adjusted": round(acc, 4),
                "recommended_multiplier": rec,
                "eligible_for_runtime": eligible,
            }
        )

    multipliers_by_fund_type: Dict[str, Dict[str, float]] = {}
    rows_by_fund_type: Dict[str, List[Dict[str, object]]] = {}
    for ft, ft_stats in stats_by_fund_type.items():
        ft_rows_ok = sum(int(v["rows"]) for v in ft_stats.values())
        ft_threshold = _dynamic_threshold(
            base_min_samples=int(min_samples),
            floor_min_samples=int(min_samples_floor),
            available_rows=ft_rows_ok,
            enable_dynamic=bool(enable_dynamic_min_samples),
        )
        ft_rows: List[Dict[str, object]] = []
        ft_mult: Dict[str, float] = {}
        for source, v in sorted(ft_stats.items(), key=lambda kv: kv[1]["total_weight"], reverse=True):
            total_w = float(v["total_weight"])
            matched_w = float(v["matched_weight"])
            rows_count = int(v["rows"])
            acc_raw = (matched_w / total_w) if total_w > 0 else 0.0
            if enable_uncertainty_shrinkage and total_w > 0:
                acc = (matched_w + 0.5 * shrinkage_strength) / (total_w + shrinkage_strength)
            else:
                acc = acc_raw
            eligible = total_w >= ft_threshold
            if eligible:
                raw = 1.0 + (acc - 0.5) * sensitivity
                rec = round(_clamp(raw, min_multiplier, max_multiplier), 4)
                ft_mult[source] = rec
            else:
                rec = 1.0
            ft_rows.append(
                {
                    "fund_type": ft,
                    "source": source,
                    "rows": rows_count,
                    "effective_samples": round(total_w, 4),
                    "effective_matched": round(matched_w, 4),
                    "accuracy_raw": round(acc_raw, 4),
                    "accuracy_adjusted": round(acc, 4),
                    "recommended_multiplier": rec,
                    "eligible_for_runtime": eligible,
                }
            )
        rows_by_fund_type[ft] = ft_rows
        multipliers_by_fund_type[ft] = ft_mult

    multipliers_by_horizon: Dict[str, Dict[str, float]] = {}
    rows_by_horizon: Dict[str, List[Dict[str, object]]] = {}
    for hz, hz_stats in stats_by_horizon.items():
        hz_rows_ok = sum(int(v["rows"]) for v in hz_stats.values())
        hz_threshold = _dynamic_threshold(
            base_min_samples=int(min_samples),
            floor_min_samples=int(min_samples_floor),
            available_rows=hz_rows_ok,
            enable_dynamic=bool(enable_dynamic_min_samples),
        )
        hz_rows: List[Dict[str, object]] = []
        hz_mult: Dict[str, float] = {}
        for source, v in sorted(hz_stats.items(), key=lambda kv: kv[1]["total_weight"], reverse=True):
            total_w = float(v["total_weight"])
            matched_w = float(v["matched_weight"])
            rows_count = int(v["rows"])
            acc_raw = (matched_w / total_w) if total_w > 0 else 0.0
            if enable_uncertainty_shrinkage and total_w > 0:
                acc = (matched_w + 0.5 * shrinkage_strength) / (total_w + shrinkage_strength)
            else:
                acc = acc_raw
            eligible = total_w >= hz_threshold
            if eligible:
                raw = 1.0 + (acc - 0.5) * sensitivity
                rec = round(_clamp(raw, min_multiplier, max_multiplier), 4)
                hz_mult[source] = rec
            else:
                rec = 1.0
            hz_rows.append(
                {
                    "horizon": hz,
                    "source": source,
                    "rows": rows_count,
                    "effective_samples": round(total_w, 4),
                    "effective_matched": round(matched_w, 4),
                    "accuracy_raw": round(acc_raw, 4),
                    "accuracy_adjusted": round(acc, 4),
                    "recommended_multiplier": rec,
                    "eligible_for_runtime": eligible,
                }
            )
        rows_by_horizon[hz] = hz_rows
        multipliers_by_horizon[hz] = hz_mult

    multipliers_by_fund_type_horizon: Dict[str, Dict[str, Dict[str, float]]] = {}
    rows_by_fund_type_horizon: Dict[str, Dict[str, List[Dict[str, object]]]] = {}
    for ft, hz_map in stats_by_fund_type_horizon.items():
        ft_hz_rows: Dict[str, List[Dict[str, object]]] = {}
        ft_hz_mult: Dict[str, Dict[str, float]] = {}
        for hz, hz_stats in hz_map.items():
            ft_hz_rows_ok = sum(int(v["rows"]) for v in hz_stats.values())
            ft_hz_threshold = _dynamic_threshold(
                base_min_samples=int(min_samples),
                floor_min_samples=int(min_samples_floor),
                available_rows=ft_hz_rows_ok,
                enable_dynamic=bool(enable_dynamic_min_samples),
            )
            rows_local: List[Dict[str, object]] = []
            mult_local: Dict[str, float] = {}
            for source, v in sorted(hz_stats.items(), key=lambda kv: kv[1]["total_weight"], reverse=True):
                total_w = float(v["total_weight"])
                matched_w = float(v["matched_weight"])
                rows_count = int(v["rows"])
                acc_raw = (matched_w / total_w) if total_w > 0 else 0.0
                if enable_uncertainty_shrinkage and total_w > 0:
                    acc = (matched_w + 0.5 * shrinkage_strength) / (total_w + shrinkage_strength)
                else:
                    acc = acc_raw
                eligible = total_w >= ft_hz_threshold
                if eligible:
                    raw = 1.0 + (acc - 0.5) * sensitivity
                    rec = round(_clamp(raw, min_multiplier, max_multiplier), 4)
                    mult_local[source] = rec
                else:
                    rec = 1.0
                rows_local.append(
                    {
                        "fund_type": ft,
                        "horizon": hz,
                        "source": source,
                        "rows": rows_count,
                        "effective_samples": round(total_w, 4),
                        "effective_matched": round(matched_w, 4),
                        "accuracy_raw": round(acc_raw, 4),
                        "accuracy_adjusted": round(acc, 4),
                        "recommended_multiplier": rec,
                        "eligible_for_runtime": eligible,
                    }
                )
            ft_hz_rows[hz] = rows_local
            ft_hz_mult[hz] = mult_local
        rows_by_fund_type_horizon[ft] = ft_hz_rows
        multipliers_by_fund_type_horizon[ft] = ft_hz_mult

    return {
        "min_samples": int(min_samples),
        "min_samples_floor": int(min_samples_floor),
        "enable_dynamic_min_samples": bool(enable_dynamic_min_samples),
        "effective_threshold_global": round(global_threshold, 4),
        "half_life_days": int(half_life_days),
        "decay_floor": float(decay_floor),
        "enable_uncertainty_shrinkage": bool(enable_uncertainty_shrinkage),
        "shrinkage_strength": float(shrinkage_strength),
        "sensitivity": float(sensitivity),
        "min_multiplier": float(min_multiplier),
        "max_multiplier": float(max_multiplier),
        "source_performance": rows,
        "source_multipliers": multipliers,
        "source_performance_by_fund_type": rows_by_fund_type,
        "source_multipliers_by_fund_type": multipliers_by_fund_type,
        "source_performance_by_horizon": rows_by_horizon,
        "source_multipliers_by_horizon": multipliers_by_horizon,
        "source_performance_by_fund_type_horizon": rows_by_fund_type_horizon,
        "source_multipliers_by_fund_type_horizon": multipliers_by_fund_type_horizon,
    }
