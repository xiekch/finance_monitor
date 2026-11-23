from datetime import date

from analyzers.advice_facts import check_reference_price, price_line, prompt_facts, window_facts
from fetchers.price_history import DailyBar
from models.advice import parse_advice_markdown, replace_review_line


def _bars():
    # 房地产 ETF 的真实走势片段：参考价 1.142，目标价 1.206（上方），失效价 1.071（下方）
    rows = [
        (date(2026, 11, 9), 1.141, 1.153, 1.128, 1.129),
        (date(2026, 11, 12), 1.145, 1.155, 1.132, 1.133),
        (date(2026, 11, 17), 1.088, 1.098, 1.078, 1.082),
        (date(2026, 11, 18), 1.084, 1.088, 1.066, 1.078),
        (date(2026, 11, 19), 1.075, 1.080, 1.053, 1.057),
        (date(2026, 11, 20), 1.045, 1.050, 1.011, 1.011),
    ]
    return [DailyBar(*r) for r in rows]


def _doc_nov(advice_md, **kw):
    doc = parse_advice_markdown(advice_md(
        26, symbol="512200", direction="观望偏空", reference_price=1.142, target_price=1.206,
        stop_price=1.071, expiry=date(2026, 11, 20), **kw))
    doc.created_at, doc.reference_date = date(2026, 11, 8), date(2026, 11, 6)
    return doc


def test_target_not_touched_and_stop_touched_intraday(advice_md):
    facts = window_facts(_doc_nov(advice_md), _bars(), today=date(2026, 11, 21))
    assert facts.target_touch is None
    assert facts.stop_touch.day == date(2026, 11, 18)       # 最低 1.066 <= 1.071
    assert facts.high.day == date(2026, 11, 12) and facts.high.high == 1.155
    assert facts.low.day == date(2026, 11, 20) and facts.low.low == 1.011
    assert facts.last.close == 1.011
    assert facts.end == date(2026, 11, 20)                   # 取 min(今天, 到期日)


def test_touch_uses_high_for_levels_above_and_low_for_levels_below(advice_md):
    doc = _doc_nov(advice_md)
    doc.target_price = 1.155   # 恰好等于最高价，也算碰到
    doc.stop_price = 1.066     # 恰好等于最低价，也算碰到
    facts = window_facts(doc, _bars(), today=date(2026, 11, 21))
    assert facts.target_touch.day == date(2026, 11, 12)
    assert facts.stop_touch.day == date(2026, 11, 18)


def test_window_ignores_bars_before_creation_and_after_today(advice_md):
    doc = _doc_nov(advice_md)
    facts = window_facts(doc, _bars(), today=date(2026, 11, 12))
    assert [b.day for b in facts.bars] == [date(2026, 11, 9), date(2026, 11, 12)]
    assert facts.stop_touch is None


def test_no_trading_days_in_window_gives_none(advice_md):
    assert window_facts(_doc_nov(advice_md), [], today=date(2026, 11, 21)) is None
    assert window_facts(_doc_nov(advice_md), _bars(), today=date(2026, 11, 8)) is None



def test_price_line_is_single_line_with_facts_and_no_url(advice_md):
    doc = _doc_nov(advice_md)
    facts = window_facts(doc, _bars(), today=date(2026, 11, 21))
    line = price_line(doc, facts)
    assert "\n" not in line and "http" not in line
    assert "参考价 1.142（11/6）" in line and "目标价 1.206" in line and "失效价 1.071" in line
    assert "最高 1.155（11/12）" in line and "最低 1.011（11/20）" in line
    assert "最后收 1.011（11/20）" in line
    assert "目标价未碰到" in line
    assert "失效价11/18盘中碰到（开 1.084 高 1.088 低 1.066 收 1.078）" in line
    assert line.endswith("数据：Yahoo Finance 日 K（未复权）。")


def test_prompt_facts_lists_following_closes_and_daily_bars(advice_md):
    doc = _doc_nov(advice_md)
    text = prompt_facts(doc, window_facts(doc, _bars(), today=date(2026, 11, 21)))
    assert "目标价 1.206（高于参考价 1.142）：窗口内盘中没有碰到。" in text
    assert "失效价 1.071（低于参考价 1.142）：11/18盘中碰到" in text
    assert "之后两个交易日收盘 1.057（11/19）、1.011（11/20）" in text
    assert "\n11/9 开 1.141 高 1.153 低 1.128 收 1.129" in text
    assert text.count("\n11/") == 6    # 逐日 6 根



def test_check_reference_price_accepts_close_and_intraday_range():
    bars = [DailyBar(date(2026, 11, 6), 140, 143, 136, 140)]
    check = lambda p: check_reference_price(p, bars, date(2026, 11, 6), 0.02)
    assert check(140) is None
    assert check(142.5) is None       # 离收盘 1.8%
    assert check(137) is None         # 偏离收盘 2.1%，但在当天最高最低之间
    assert "对不上" in check(150)     # 区间之外
    assert "收 140" in check(150) and "136–143" in check(150)
    assert "对不上" in check(120)



def test_replace_review_line_only_touches_the_marked_line():
    note = "## 复盘 2026-11-21 到期结案\n- 结论：➖ x\n- 价格：模型自己写的 1.2345\n- 逻辑：y\n"
    out = replace_review_line(note, "- 价格：", "程序写的")
    assert "- 价格：程序写的" in out and "模型自己写的" not in out
    assert "- 结论：➖ x" in out and "- 逻辑：y" in out and out.endswith("\n")
    assert replace_review_line("NO_NEW_FINDING", "- 价格：", "z") == "NO_NEW_FINDING"
