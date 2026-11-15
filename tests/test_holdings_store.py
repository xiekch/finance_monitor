from datetime import date

from storage.holdings_store import HoldingsReportStore


def test_save_writes_report_and_actions(tmp_path):
    store = HoldingsReportStore(tmp_path)
    path = store.save(date(2026, 11, 15), "# 持仓报告\n", {"600519": "持有"})
    assert path == tmp_path / "2026-11-15.md"
    assert path.read_text(encoding="utf-8") == "# 持仓报告\n"
    assert store.latest_actions(date(2026, 11, 15)) == (date(2026, 11, 15), {"600519": "持有"})
    assert not list(tmp_path.glob("*.tmp"))


def test_latest_actions_picks_most_recent_within_window(tmp_path):
    store = HoldingsReportStore(tmp_path)
    store.save(date(2026, 11, 1), "old", {"600519": "清仓"})
    assert store.latest_actions(date(2026, 11, 15)) is None

    store.save(date(2026, 11, 12), "a", {"600519": "减仓"})
    store.save(date(2026, 11, 13), "b", {"600519": "持有"})
    store.save(date(2026, 11, 20), "future", {"600519": "加仓"})
    assert store.latest_actions(date(2026, 11, 15)) == (date(2026, 11, 13), {"600519": "持有"})


def test_latest_actions_skips_broken_files(tmp_path):
    store = HoldingsReportStore(tmp_path)
    store.save(date(2026, 11, 13), "b", {"600519": "持有"})
    (tmp_path / "2026-11-14.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    assert store.latest_actions(date(2026, 11, 15)) == (date(2026, 11, 13), {"600519": "持有"})


def test_save_raw_keeps_report_and_actions_untouched(tmp_path):
    store = HoldingsReportStore(tmp_path / "reports")
    path = store.save_raw(date(2026, 11, 15), "今天没有结论。")
    assert path.name == "2026-11-15-raw.md"
    assert path.read_text(encoding="utf-8") == "今天没有结论。"
    assert store.latest_actions(date(2026, 11, 15)) is None
