"""社交/简报时间戳统一为 UTC ISO8601（秒精度，+00:00）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_TWITTER_FMT = "%a %b %d %H:%M:%S %z %Y"


def to_utc_iso(dt: datetime) -> str:
    """任意 datetime → UTC ISO 字符串，便于 SQLite 字典序比较。"""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def window_since(hours: int) -> datetime:
    """回看窗口起点（UTC aware）。"""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def normalize_timestamp(value: str) -> str:
    """解析常见时间字符串并规范为 UTC ISO；无法解析则原样返回。"""
    if not value:
        return value
    dt = _parse_timestamp(value)
    return to_utc_iso(dt) if dt else value


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, _TWITTER_FMT)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
