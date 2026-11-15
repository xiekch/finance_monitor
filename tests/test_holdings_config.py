import pytest

from models.holdings import HoldingsConfigError, parse_holdings_config, symbol_key
from storage.holdings_store import load_holdings_config

VALID = {
    "cash": {"CNY": 50000, "USD": 2000},
    "rules": {"max_position_pct": 20, "min_cash_pct": 10, "horizon": "一年以上"},
    "holdings": [
        {"symbol": "600519", "market": "sh", "name": "贵州茅台", "quantity": 100, "cost": 1500,
         "thesis": "高端白酒龙头", "exit_when": "连续两个季度营收负增长"},
        {"symbol": "00700", "market": "HK", "name": "腾讯控股", "quantity": 200, "cost": 380},
        {"symbol": "NVDA", "market": "US", "name": "英伟达", "quantity": 30, "cost": 120.5},
        {"symbol": "CU0", "market": "FUT", "name": "沪铜主力", "quantity": 1, "cost": 80000,
         "multiplier": 5},
    ],
}

TOML = """
[cash]
CNY = 50000

[[holdings]]
symbol = "600519"
market = "SH"
name = "贵州茅台"
quantity = 100
cost = 1500
"""


def _errors(data) -> str:
    with pytest.raises(HoldingsConfigError) as info:
        parse_holdings_config(data)
    return str(info.value)


def test_valid_config():
    config = parse_holdings_config(VALID)
    assert [h.symbol for h in config.holdings] == ["600519", "00700", "NVDA", "CU0"]
    assert [h.currency for h in config.holdings] == ["CNY", "HKD", "USD", "CNY"]
    assert config.holdings[0].market == "SH"
    assert config.holdings[0].thesis == "高端白酒龙头"
    assert config.holdings[1].thesis == "" and config.holdings[1].multiplier == 1
    assert config.holdings[3].multiplier == 5
    assert config.cash == {"CNY": 50000, "USD": 2000}
    assert config.rules.max_position_pct == 20
    assert config.rules.horizon == "一年以上"


def test_cash_and_rules_are_optional():
    config = parse_holdings_config({"holdings": VALID["holdings"][:1]})
    assert config.cash == {}
    assert config.rules.max_position_pct is None and config.rules.min_cash_pct is None


def test_all_problems_reported_together():
    text = _errors({
        "cash": {"EUR": 100, "CNY": -1},
        "rules": {"max_position_pct": 150, "risk": "低"},
        "holdings": [
            {"symbol": "600519", "market": "SH", "name": "贵州茅台", "quantity": 0, "cost": 1500},
            {"symbol": 700, "market": "HK", "name": "腾讯控股", "quantity": 1, "cost": 1},
            {"symbol": "AAPL", "market": "NASDAQ2", "name": "苹果", "quantity": 1, "cost": -3},
            {"symbol": "MSFT", "market": "US", "quantity": 1, "cost": 1, "quanity": 2},
        ],
    })
    for needle in (
        "EUR", "CNY", "max_position_pct", "risk",
        "quantity", "symbol 要写成带引号的字符串", "NASDAQ2", "cost",
        "缺少 name", "quanity",
    ):
        assert needle in text


def test_duplicate_symbol_rejected():
    holding = VALID["holdings"][0]
    assert "重复" in _errors({"holdings": [holding, dict(holding)]})


def test_empty_config_rejected():
    assert "没有持仓" in _errors({})
    assert "holdings" in _errors({"holdings": {"symbol": "600519"}})


def test_cash_only_is_allowed():
    config = parse_holdings_config({"cash": {"CNY": 1000}})
    assert config.holdings == [] and config.cash == {"CNY": 1000}


def test_bool_is_not_a_number():
    text = _errors({"holdings": [
        {"symbol": "600519", "market": "SH", "name": "贵州茅台", "quantity": True, "cost": 1},
    ]})
    assert "quantity" in text


def test_symbol_key():
    assert symbol_key("0700.HK") == symbol_key("00700") == "700"
    assert symbol_key("SH600519") == symbol_key("600519.SS") == "600519"
    assert symbol_key(" nvda ") == "NVDA"
    assert symbol_key("btcusdt") == "BTCUSDT"


def test_load_missing_file_points_to_example(tmp_path):
    with pytest.raises(HoldingsConfigError) as info:
        load_holdings_config(tmp_path / "holdings.toml")
    assert "holdings.example.toml" in str(info.value)


def test_load_reports_toml_syntax_error(tmp_path):
    path = tmp_path / "holdings.toml"
    path.write_text('[[holdings]]\nsymbol = 00700\n', encoding="utf-8")
    with pytest.raises(HoldingsConfigError) as info:
        load_holdings_config(path)
    assert "格式错误" in str(info.value)


def test_load_reads_file_every_time(tmp_path):
    path = tmp_path / "holdings.toml"
    path.write_text(TOML, encoding="utf-8")
    assert load_holdings_config(path).holdings[0].quantity == 100
    path.write_text(TOML.replace("quantity = 100", "quantity = 300"), encoding="utf-8")
    assert load_holdings_config(path).holdings[0].quantity == 300


def test_example_file_is_valid():
    from config.holdings import HOLDINGS_EXAMPLE_FILE
    config = load_holdings_config(HOLDINGS_EXAMPLE_FILE)
    assert config.holdings and config.cash
