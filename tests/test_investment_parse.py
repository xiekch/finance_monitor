from datetime import date

from models.advice import parse_advice_markdown
from steps.investment_parse import (
    build_advice_prompt,
    build_review_prompt,
    parse_advice_response,
    parse_review_response,
)


def _block(symbol, expiry="2026-11-09", target=160):
    return f"""# 建议 {symbol}
- symbol: {symbol}
- name: 测试
- direction: 看多
- expiry_date: {expiry}
- currency: USD
- reference_price: 140
- reference_date: 2026-10-26
- reference_url: https://example.com/{symbol}
- target_price: {target}
- stop_price: 120

## 理由
需求还在。

## 目标价
160 附近。

## 失效条件
跌破 120。

## 参考价
140 收盘。

## 观察条件
财报。
"""


def test_parse_tolerates_preamble_bold_keys_and_fullwidth_colon():
    raw = "好的，以下是今天的建议。\n\n" + _block("NVDA").replace(
        "- symbol: NVDA", "- **symbol**：NVDA"
    ).replace("- reference_url: https://example.com/NVDA", "- reference_url: <https://example.com/NVDA>")
    valid, dropped = parse_advice_response(raw, today=date(2026, 10, 26), open_symbols=set())
    assert dropped == 0
    assert valid[0].symbol == "NVDA"
    assert valid[0].reference_url == "https://example.com/NVDA"
    assert valid[0].sections["观察条件"] == "财报。"


def test_parse_drops_invalid_and_already_open():
    raw = "\n".join([_block("NVDA"), _block("BAD", expiry="2027-01-01"), _block("AAPL")])
    valid, dropped = parse_advice_response(raw, today=date(2026, 10, 26), open_symbols={"AAPL"})
    assert [d.symbol for d in valid] == ["NVDA"]
    assert valid[0].created_at == date(2026, 10, 26)
    assert dropped == 2


def test_parse_drops_duplicate_in_batch_and_caps_at_three():
    raw = "\n".join([_block("NVDA"), _block("NVDA"), _block("A"), _block("B"), _block("C")])
    valid, dropped = parse_advice_response(raw, today=date(2026, 10, 26), open_symbols=set())
    assert [d.symbol for d in valid] == ["NVDA", "A", "B"]
    assert dropped == 2


def test_review_sentinel_and_note():
    assert parse_review_response("NO_NEW_FINDING", kind="weekly") is None
    note = parse_review_response("""## 复盘 2026-10-26 周回溯
- 价格：未碰到目标价。
- 逻辑：催化剂未落地。
- 事件过程：本周没有新订单。
- 经验：无
""", kind="weekly")
    assert "周回溯" in note


def test_advice_prompt_includes_history_only():
    prompt = build_advice_prompt(
        today=date(2026, 10, 26),
        open_summaries=["2026-10-20-1 | NVDA 英伟达 | 看多 | 到期 2026-11-09 | 目标价 160 | 需求还在。 | 尚无复盘"],
        lessons=["## 2026-10-25 · NVDA · 2026-10-01-1 · 到期结案\n别把叙事写成已兑现。"],
    )
    assert "2026-10-20-1" in prompt
    assert "别把叙事写成已兑现" in prompt
    assert "不使用已抓取的行情" in prompt
    assert "不要再发新建议" in prompt
    assert "advice/lessons.md" in prompt
    assert "只读" in prompt
    assert "0700.HK" in prompt
    assert "# 建议 1" in prompt
    assert "<<<" not in prompt


def test_review_prompt_window_stops_at_expiry(advice_md):
    doc = parse_advice_markdown(advice_md(19, expiry=date(2026, 10, 25)))
    doc.id = "2026-10-19-1"
    prompt = build_review_prompt(doc, kind="monthly", today=date(2026, 11, 1))
    assert "2026-10-19 至 2026-10-25" in prompt
    assert "NO_NEW_FINDING" in prompt
