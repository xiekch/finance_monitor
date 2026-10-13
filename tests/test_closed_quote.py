"""收盘后仍取当日收盘价；新浪没有时才用今天的分钟线。"""
import asyncio
from datetime import datetime, timedelta

from models.market import PriceData
from fetchers.astock_fetcher import AStockFetcher
from fetchers.futures_fetcher import FuturesFetcher


def _bar(symbol, market, close, *, days_ago=0):
    return PriceData(
        symbol=symbol,
        market=market,
        timestamp=datetime.now() - timedelta(days=days_ago),
        open=close,
        high=close,
        low=close,
        close=close,
        frequency="1m",
    )


def test_ashare_after_close_uses_sina_close():
    fetcher = AStockFetcher({})
    price = _bar("600519", "SH", 1270)

    async def fake_sina(symbols):
        return [price]

    fetcher._fetch_sina_ashares = fake_sina
    out = asyncio.run(fetcher.fetch_realtime_data([
        {"symbol": "600519", "market": "SH", "name": "茅台"},
    ]))
    assert [p.close for p in out] == [1270]


def test_ashare_falls_back_to_todays_minute_bar():
    fetcher = AStockFetcher({})
    bar = _bar("600519", "SH", 1260)

    async def fake_sina(symbols):
        return []

    fetcher._fetch_sina_ashares = fake_sina
    fetcher._get_latest_from_db = lambda info: bar
    out = asyncio.run(fetcher.fetch_realtime_data([
        {"symbol": "600519", "market": "SH", "name": "茅台"},
    ]))
    assert [p.close for p in out] == [1260]


def test_ashare_ignores_yesterdays_minute_bar():
    fetcher = AStockFetcher({})

    async def fake_sina(symbols):
        return []

    fetcher._fetch_sina_ashares = fake_sina
    fetcher._get_latest_from_db = lambda info: _bar("600519", "SH", 1200, days_ago=1)
    out = asyncio.run(fetcher.fetch_realtime_data([
        {"symbol": "600519", "market": "SH", "name": "茅台"},
    ]))
    assert out == []


def test_futures_after_close_uses_sina_then_todays_minute():
    fetcher = FuturesFetcher({})
    sina_price = _bar("AU0", "FUT", 905)
    minute = _bar("AG0", "FUT", 8)

    async def fake_sina(symbols):
        return [sina_price]

    fetcher._fetch_sina_futures = fake_sina
    fetcher._today_minute = lambda symbol, market: minute if symbol == "AG0" else None
    out = asyncio.run(fetcher.fetch_realtime_data([
        {"symbol": "AU0", "market": "FUT", "name": "黄金"},
        {"symbol": "AG0", "market": "FUT", "name": "白银"},
    ]))
    assert [(p.symbol, p.close) for p in out] == [("AU0", 905), ("AG0", 8)]
