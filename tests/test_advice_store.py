from datetime import date
from pathlib import Path

import pytest

from models.advice import parse_advice_markdown
from storage.advice_store import AdviceStore, previous_month, previous_week


def _save(store, advice_md, *args, **kwargs):
    return store.save_new(parse_advice_markdown(advice_md(*args, **kwargs)))


def test_save_puts_file_in_month_dir_and_assigns_id(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    first = _save(store, advice_md, 26)
    second = _save(store, advice_md, 26, symbol="AAPL")
    assert first.id == "2026-10-26-1"
    assert second.id == "2026-10-26-2"
    assert (tmp_path / "2026-10" / "2026-10-26-1.md").is_file()
    assert not list(tmp_path.rglob("*.tmp"))


def test_due_includes_missed_and_week_month_cohorts(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    _save(store, advice_md, 19, expiry=date(2026, 10, 25))
    _save(store, advice_md, 10, symbol="MISSED", expiry=date(2026, 10, 20))
    _save(store, advice_md, 15, symbol="DONE", status="closed", expiry=date(2026, 10, 22))
    _save(store, advice_md, 25, symbol="AAPL", expiry=date(2026, 11, 20))
    today = date(2026, 10, 26)
    assert [d.created_at.day for d in store.list_due(today)] == [10, 19]
    start, end = previous_week(today)
    assert (start, end) == (date(2026, 10, 19), date(2026, 10, 25))
    assert [d.created_at.day for d in store.list_created_between(start, end)] == [19, 25]
    assert previous_month(date(2026, 11, 1)) == (date(2026, 10, 1), date(2026, 10, 31))


def test_open_summaries_use_price_and_logic_lines(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    _save(store, advice_md, 26)
    _save(store, advice_md, 25, symbol="AAPL", reviews=(
        "\n## 复盘 2026-10-26 周回溯\n"
        "- 价格：未碰到目标价。\n"
        "- 逻辑：催化剂未落地。\n"
        "- 事件过程：无。\n"
        "- 经验：无\n"
    ))
    _save(store, advice_md, 20, symbol="OLD", status="closed", expiry=date(2026, 10, 25))
    _save(store, advice_md, 1, symbol="STALE", expiry=date(2026, 10, 25))
    lines = store.open_summaries(date(2026, 10, 26))
    assert len(lines) == 2
    nvda = next(line for line in lines if "NVDA" in line)
    aapl = next(line for line in lines if "AAPL" in line)
    assert "尚无复盘" in nvda
    assert "需求还在。" in nvda and "后面还有一句" not in nvda
    assert "未碰到目标价" in aapl and "催化剂未落地" in aapl
    assert "## 复盘" not in aapl
    assert store.open_symbols(date(2026, 10, 26)) == {"NVDA", "AAPL"}


def test_last_30_lessons(tmp_path: Path):
    store = AdviceStore(tmp_path)
    for i in range(35):
        store.append_lesson(f"经验 {i}", advice_id="x", symbol="NVDA", kind="到期结案", on=date(2026, 10, 1))
    recent = "\n".join(store.recent_lessons(30))
    assert len(store.recent_lessons(30)) == 30
    assert "经验 4\n" not in recent + "\n"
    assert "经验 5" in recent and "经验 34" in recent


DUE_NOTE = """## 复盘 2026-10-26 到期结案
- 价格：建议时 140 美元，目标价 160 美元，结案时 151 美元。窗口内未碰到目标价。来源 https://example.com/close
- 逻辑：需求仍在。
- 事件过程：10 月下旬订单评论偏多。
- 经验：目标价没碰到就不把叙事写成已兑现。
"""


def test_due_review_appends_and_closes_without_rewriting_thesis(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 25, expiry=date(2026, 10, 25))
    updated = store.append_review(saved.id, DUE_NOTE, kind="due")
    assert updated.status == "closed"
    text = (tmp_path / "2026-10" / f"{saved.id}.md").read_text(encoding="utf-8")
    assert text.index("## 理由") < text.index("## 复盘 2026-10-26 到期结案")
    assert "需求还在。" in text
    assert "目标价没碰到" in store.recent_lessons(30)[0]


def test_due_no_new_finding_raises_and_stays_open(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 25, expiry=date(2026, 10, 25))
    with pytest.raises(ValueError):
        store.append_review(saved.id, "NO_NEW_FINDING", kind="due")
    assert store.load(saved.id).status == "open"


def test_weekly_no_new_finding_does_not_write(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 19)
    path = tmp_path / "2026-10" / f"{saved.id}.md"
    before = path.read_text(encoding="utf-8")
    assert store.append_review(saved.id, "NO_NEW_FINDING", kind="weekly") is None
    assert path.read_text(encoding="utf-8") == before


def test_second_review_sees_first(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 25, expiry=date(2026, 10, 25))
    store.append_review(saved.id, DUE_NOTE.replace("- 经验：目标价没碰到就不把叙事写成已兑现。", "- 经验：无"), kind="due")
    again = store.load(saved.id)
    assert any("结案时 151" in review for review in again.reviews)
    assert store.recent_lessons(30) == []
