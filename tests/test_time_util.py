from datetime import timezone

from utils.time_util import normalize_timestamp, window_since


def test_twitter_format_to_utc_iso():
    raw = "Mon Jun 01 04:58:38 +0000 2026"
    assert normalize_timestamp(raw) == "2026-06-01T04:58:38+00:00"


def test_utc_string_compare_matches_chronology():
    """修复前 naive local since 与 UTC created_at 字典序比较会出错。"""
    since_iso = "2026-06-16T00:50:00+00:00"
    assert "2026-06-16T01:00:00+00:00" >= since_iso
    assert "2026-06-16T00:30:00+00:00" < since_iso


def test_normalize_idempotent():
    iso = "2026-06-01T04:58:38+00:00"
    assert normalize_timestamp(iso) == iso


def test_window_since_is_utc_aware():
    since = window_since(12)
    assert since.tzinfo == timezone.utc
