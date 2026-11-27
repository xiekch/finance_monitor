import asyncio

from analyzers.threshold_manager import ThresholdManager
from config.minute_targets import minute_stock_targets
from models.holdings import HoldingsConfigError, parse_holdings_config

import pytest

HOLDINGS_TOML = """
[[holdings]]
symbol = "600519"
market = "SH"
name = "贵州茅台"
quantity = 100
cost = 1500

[[holdings]]
symbol = "159605"
market = "SZ"
name = "中概互联ETF"
quantity = 1000
cost = 1
alert_window_pct = 0.8
alert_day_pct = 2

[[holdings]]
symbol = "00700"
market = "HK"
name = "腾讯控股"
quantity = 100
cost = 380

[[holdings]]
symbol = "NVDA"
market = "US"
name = "英伟达"
quantity = 10
cost = 120

[[holdings]]
symbol = "BTCUSDT"
market = "CRYPTO"
name = "Bitcoin"
quantity = 1
cost = 60000

[[holdings]]
symbol = "AU0"
market = "FUT"
name = "黄金"
quantity = 1
cost = 580
"""


@pytest.fixture(autouse=True)
def no_index_targets(monkeypatch):
    """默认只看持仓；大盘指数的合并在单独的测试里验证。"""
    import config.minute_targets as mt
    monkeypatch.setattr(mt, "MONITOR_CONFIG", {"stocks": []})


@pytest.fixture
def holdings_file(tmp_path):
    path = tmp_path / "holdings.toml"
    path.write_text(HOLDINGS_TOML, encoding="utf-8")
    return path


def test_only_stock_holdings_become_minute_targets(holdings_file):
    targets = minute_stock_targets(holdings_file)
    assert [(t["symbol"], t["market"]) for t in targets] == [
        ("600519", "SH"), ("159605", "SZ"), ("00700", "HK"), ("NVDA", "US"),
    ]
    assert all(t["frequency"] == "minute" for t in targets)
    # 持仓数量和成本价不会带进监控配置
    assert all(
        set(t) == {"name", "symbol", "market", "frequency", "threshold", "prev_close_threshold"}
        for t in targets
    )


def test_threshold_defaults_by_market_and_per_holding_override(holdings_file):
    targets = minute_stock_targets(holdings_file)
    window = {t["symbol"]: t["threshold"] for t in targets}
    day = {t["symbol"]: t["prev_close_threshold"] for t in targets}
    assert window == {"600519": 1.5, "159605": 0.8, "00700": 1.5, "NVDA": 2.0}
    assert day == {"600519": 3.0, "159605": 2.0, "00700": 3.0, "NVDA": 4.0}


def test_missing_or_broken_file_gives_no_targets(tmp_path):
    assert minute_stock_targets(tmp_path / "nope.toml") == []
    bad = tmp_path / "bad.toml"
    bad.write_text("[[holdings]]\nsymbol = 700\n", encoding="utf-8")
    assert minute_stock_targets(bad) == []


@pytest.mark.parametrize("key", ["alert_day_pct", "alert_window_pct"])
def test_alert_pct_must_be_positive(key):
    with pytest.raises(HoldingsConfigError, match=f"{key} 必须是正数"):
        parse_holdings_config({"holdings": [
            {"symbol": "600519", "market": "SH", "name": "茅台", "quantity": 1, "cost": 1,
             key: 0},
        ]})


def test_threshold_manager_follows_holdings_changes(holdings_file):
    manager = ThresholdManager()
    manager.reload_minute_targets(minute_stock_targets(holdings_file))
    assert manager.get_threshold("159605", "minute", market="SZ") == 0.8
    assert manager.get_threshold("159605", "prev_close", market="SZ") == 2.0
    assert manager.get_name("159605", "SZ") == "中概互联ETF"
    assert manager.get_threshold("NVDA", "minute", market="US") == 2.0

    # 卖掉英伟达后，分钟级阈值回到默认值，不再沿用持仓里的设置
    manager.reload_minute_targets([
        {"name": "贵州茅台", "symbol": "600519", "market": "SH", "frequency": "minute",
         "threshold": 1.2, "prev_close_threshold": 5.0},
    ])
    assert manager.get_threshold("600519", "prev_close", market="SH") == 5.0
    assert manager.get_threshold("159605", "prev_close", market="SZ") == 3.0  # 回到默认值
    assert manager.get_threshold("600519", "minute", market="SH") == 1.2
    assert manager.get_threshold("NVDA", "minute", market="US") == 2.0  # 默认值恰好也是 2.0
    assert manager.get_threshold("159605", "minute", market="SZ") == 2.0


def test_fetch_steps_read_holdings(monkeypatch, holdings_file):
    import steps.fetch.astock as astock
    import steps.fetch.usstock as usstock

    targets = minute_stock_targets(holdings_file)
    monkeypatch.setattr(astock, "minute_stock_targets", lambda: targets)
    monkeypatch.setattr(usstock, "minute_stock_targets", lambda: targets)

    seen = {}

    async def a_realtime(self, symbols):
        seen["astock"] = [s["symbol"] for s in symbols]
        return []

    async def us_realtime(self, symbols):
        seen["usstock"] = [s["symbol"] for s in symbols]
        return []

    monkeypatch.setattr(astock.FetchAStock, "_fetch_realtime", a_realtime)
    monkeypatch.setattr(usstock.FetchUSStock, "_fetch_realtime", us_realtime)

    asyncio.run(astock.FetchAStock("minute").process([]))
    asyncio.run(usstock.FetchUSStock("minute").process([]))
    assert seen == {"astock": ["600519", "159605"], "usstock": ["00700", "NVDA"]}


def test_index_targets_merge_with_holdings(monkeypatch, holdings_file, tmp_path):
    import config.minute_targets as mt
    monkeypatch.setattr(mt, "MONITOR_CONFIG", {"stocks": [
        {"name": "上证指数", "symbol": "000001", "market": "SH", "frequency": "minute",
         "threshold": 0.8, "prev_close_threshold": 2.5},
        {"name": "沪深300", "symbol": "000300", "market": "SH", "frequency": "minute",
         "threshold": 0.8},                                    # 没写昨收阈值 → 默认值
        {"name": "苹果", "symbol": "AAPL", "market": "US", "frequency": "daily", "threshold": 1.5},
        {"name": "日经225", "symbol": "^N225", "market": "JP", "frequency": "minute",
         "threshold": 1.0},                                    # 非盯盘市场，忽略
        {"name": "茅台旧配置", "symbol": "600519", "market": "SH", "frequency": "minute",
         "threshold": 9.9, "prev_close_threshold": 9.9},       # 和持仓重复 → 持仓优先
    ]})
    by_symbol = {t["symbol"]: t for t in minute_stock_targets(holdings_file)}
    assert list(by_symbol) == ["000001", "000300", "600519", "159605", "00700", "NVDA"]
    assert by_symbol["000001"]["prev_close_threshold"] == 2.5
    assert by_symbol["000300"]["prev_close_threshold"] == 3.0
    assert by_symbol["600519"]["name"] == "贵州茅台" and by_symbol["600519"]["threshold"] == 1.5

    # 持仓读不到时，仍然盯大盘指数
    only = minute_stock_targets(tmp_path / "nope.toml")
    assert [t["symbol"] for t in only] == ["000001", "000300", "600519"]


def test_default_config_has_index_minute_targets():
    import config.monitor as monitor
    from config.minute_targets import MINUTE_STOCK_MARKETS
    mins = [a for a in monitor.MONITOR_CONFIG["stocks"] if a["frequency"] == "minute"]
    assert {a["symbol"] for a in mins} == {"000001", "000300", "399001", "399006", "000688"}
    assert all(a["market"] in MINUTE_STOCK_MARKETS for a in mins)

    manager = ThresholdManager()
    assert manager.get_threshold("000001", "minute", market="SH") == 0.8
    assert manager.get_threshold("000001", "prev_close", market="SH") == 2.5
