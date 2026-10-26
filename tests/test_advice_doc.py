from datetime import date

from models.advice import normalize_symbol, parse_advice_markdown, render_advice_markdown, validate_advice


def test_roundtrip_keeps_frontmatter_and_sections(advice_md):
    doc = parse_advice_markdown(advice_md())
    again = parse_advice_markdown(render_advice_markdown(doc))
    assert again.created_at == date(2026, 10, 26)
    assert again.expiry_date == date(2026, 11, 9)
    assert again.direction == "看多"
    assert again.currency == "USD"
    assert again.reference_price == 140
    assert again.target_price == 160
    assert again.stop_price == 120
    assert again.reference_url == "https://example.com/quote"
    assert again.sections["理由"].startswith("需求还在")
    assert validate_advice(again) == []


def test_stop_price_is_optional(advice_md):
    doc = parse_advice_markdown(advice_md(stop_price=None))
    assert doc.stop_price is None
    assert "stop_price" not in render_advice_markdown(doc)
    assert validate_advice(doc) == []


def test_reject_long_target_or_stop_on_wrong_side(advice_md):
    assert any("目标价" in e for e in validate_advice(parse_advice_markdown(advice_md(target_price=140))))
    assert any("失效" in e for e in validate_advice(parse_advice_markdown(advice_md(stop_price=150))))


def test_reject_short_target_or_stop_on_wrong_side(advice_md):
    ok = parse_advice_markdown(advice_md(direction="看空", target_price=120, stop_price=150))
    assert validate_advice(ok) == []
    bad_target = parse_advice_markdown(advice_md(direction="看空", target_price=150, stop_price=160))
    assert any("目标价" in e for e in validate_advice(bad_target))
    bad_stop = parse_advice_markdown(advice_md(direction="看空", target_price=120, stop_price=130))
    assert any("失效" in e for e in validate_advice(bad_stop))


def test_watch_allows_target_on_either_side(advice_md):
    doc = parse_advice_markdown(advice_md(direction="观望", target_price=130, stop_price=None))
    assert validate_advice(doc) == []


def test_watch_stop_must_be_opposite_target(advice_md):
    below = parse_advice_markdown(advice_md(direction="观望", target_price=130, stop_price=150))
    above = parse_advice_markdown(advice_md(direction="观望", target_price=150, stop_price=130))
    assert validate_advice(below) == []
    assert validate_advice(above) == []
    same_side = parse_advice_markdown(advice_md(direction="观望", target_price=130, stop_price=120))
    assert any("失效" in e for e in validate_advice(same_side))


def test_reject_stale_or_future_reference(advice_md):
    assert validate_advice(parse_advice_markdown(advice_md(reference_date=date(2026, 10, 23)))) == []
    stale = parse_advice_markdown(advice_md(reference_date=date(2026, 10, 22)))
    assert any("参考价" in e for e in validate_advice(stale))
    future = parse_advice_markdown(advice_md(reference_date=date(2026, 10, 27)))
    assert any("参考价" in e for e in validate_advice(future))


def test_reject_expiry_beyond_31_days(advice_md):
    assert validate_advice(parse_advice_markdown(advice_md(expiry=date(2026, 11, 26)))) == []
    doc = parse_advice_markdown(advice_md(expiry=date(2026, 11, 27)))
    assert any("到期日" in e for e in validate_advice(doc))


def test_reject_symbol_already_open(advice_md):
    doc = parse_advice_markdown(advice_md())
    assert any("标的" in e for e in validate_advice(doc, open_symbols={"NVDA"}))


def test_symbol_dedup_ignores_exchange_suffix_and_case(advice_md):
    for written in ("601857.SS", "sh601857", "SH601857", " 601857 "):
        doc = parse_advice_markdown(advice_md(symbol=written))
        assert any("标的" in e for e in validate_advice(doc, open_symbols={"601857"})), written
    assert normalize_symbol("0700.hk") == "0700.HK"
    assert normalize_symbol("msft") == "MSFT"


def test_reject_empty_section(advice_md):
    doc = parse_advice_markdown(advice_md())
    doc.sections["观察条件"] = "  "
    assert any("观察条件" in e for e in validate_advice(doc))
