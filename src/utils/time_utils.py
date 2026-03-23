"""Time utility helpers for freshness windows and stale gating."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_date(date_str: str) -> datetime | None:
    """Parse flexible date strings into UTC datetime."""
    if not date_str:
        return None

    cleaned = date_str.replace("年", "-").replace("月", "-").replace("日", "")
    cleaned = cleaned.replace("/", "-").replace(".", "-").strip()
    cleaned = cleaned.split(" ", 1)[0]

    for fmt in ("%Y-%m-%d", "%y-%m-%d", "%Y-%m", "%Y%m%d"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if fmt == "%Y-%m":
                dt = dt.replace(day=1)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def age_days(date_str: str, now: datetime | None = None) -> int | None:
    """Return age in days from now; None when date is unavailable."""
    now = now or datetime.now(timezone.utc)
    dt = parse_date(date_str)
    if not dt:
        return None
    return max(0, (now - dt).days)


def freshness_bucket(date_str: str, now: datetime | None = None) -> str:
    """Map date to freshness bucket with explicit 3/7/14/30 windows."""
    days = age_days(date_str, now=now)
    if days is None:
        return "unknown"
    if days <= 3:
        return "within_3d"
    if days <= 7:
        return "within_7d"
    if days <= 14:
        return "within_14d"
    if days <= 30:
        return "within_30d"
    return "older_than_30d"


def is_stale_for_window(date_str: str, window_days: int, now: datetime | None = None) -> bool:
    """Check whether an event is stale under selected analysis window."""
    days = age_days(date_str, now=now)
    if days is None:
        return True
    return days > window_days
