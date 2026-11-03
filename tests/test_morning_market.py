"""早报行情：yfinance 失败、新浪指数冻结、库内日线过期时，不能写出崩盘涨跌幅。"""
import asyncio
import logging
from datetime import datetime, timedelta

from models.market import PriceData
from fetchers.us_stock_yf_fetcher import USStockYfFetcher
from steps.fetch.morning_data import FetchMorningData


def _pct(current: float, previous: float) -> str:
    return f"{(current - previous) / previous * 100:+.2f}%"


def _bar(symbol, market, close, day, frequency="1d"):
    return PriceData(
        symbol=symbol,
        market=market,
        timestamp=datetime.combine(day, datetime.min.time()),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=0,
        frequency=frequency,
    )


class _DB:
    def __init__(self, rows):
        self.rows = list(rows)
        self.saved = []

    def get_historical_prices(self, symbol, market, frequency, start_date, end_date):
        return [
            row for row in self.rows
            if row.symbol == symbol and row.market == market and row.frequency == frequency
        ]

    def get_latest_price(self, symbol, market, frequency):
        rows = self.get_historical_prices(symbol, market, frequency, None, None)
        return rows[-1] if rows else None

    def save_price_data(self, bar):
        self.saved.append(bar)
        return True


class _Limiter:
    async def acquire(self):
        return None


def _step(items, db_rows):
    step = FetchMorningData.__new__(FetchMorningData)
    step.name = "FetchMorningData"
    step.market_db = _DB(db_rows)
    step._collect_watchlist = lambda: items
    return step


def test_pick_prev_close_skips_the_bar_that_is_the_displayed_price():
    today = datetime.now().date()
    current = _bar("^GSPC", "US", 7580.07, today)
    rows = [
        _bar("^GSPC", "US", 7720.39, today - timedelta(days=4)),
        _bar("^GSPC", "US", 7580.07, today - timedelta(days=3)),
    ]
    picked = FetchMorningData._pick_prev_close(rows, today, current)
    assert picked.close == 7720.39


def test_pick_prev_close_keeps_flat_day_previous_close():
    today = datetime.now().date()
    current = _bar("^GSPC", "US", 100.0, today)
    rows = [
        _bar("^GSPC", "US", 100.0, today - timedelta(days=1)),
        _bar("^GSPC", "US", 100.0, today),
    ]
    picked = FetchMorningData._pick_prev_close(rows, today, current)
    assert picked is not None
    assert picked.timestamp.date() == today - timedelta(days=1)
    assert picked.close == 100.0


def test_displayed_session_is_not_reused_as_previous_close():
    """库里已经有这次现价当天的日线时，涨跌幅仍相对上一交易日，而不是 0。"""
    today = datetime.now().date()
    item = {"name": "标普500", "symbol": "^GSPC", "market": "US"}
    current = _bar("^GSPC", "US", 7580.07, today, frequency="1m")
    current.timestamp = datetime.now()
    db_rows = [
        _bar("^GSPC", "US", 7720.39, today - timedelta(days=4)),
        _bar("^GSPC", "US", 7580.07, today - timedelta(days=3)),
    ]
    step = _step([item], db_rows)

    class _Fetcher:
        def cached_daily_bars(self, symbol, market, start_date, end_date):
            return None

        async def fetch_historical_data(self, **kwargs):
            raise AssertionError("库内昨收可用时不应再打行情接口")

    step.us_fetcher = _Fetcher()

    async def _current(watchlist):
        return {("^GSPC", "US"): current}

    step._fetch_current_prices = _current
    text = asyncio.run(step._build_market_block())
    assert _pct(7580.07, 7720.39) in text
    assert "+0.00%" not in text


def test_crash_level_index_move_is_not_written(caplog):
    """2026-11-02 早报：(6643.70 - 7623.68) / 7623.68 = -12.85%。"""
    assert _pct(6643.70, 7623.68) == "-12.85%"
    item = {"name": "标普500", "symbol": "^GSPC", "market": "US"}
    current = _bar("^GSPC", "US", 6643.70, datetime.now().date(), frequency="1m")
    previous = _bar("^GSPC", "US", 7623.68, datetime.now().date() - timedelta(days=10))
    with caplog.at_level(logging.WARNING):
        row = FetchMorningData._build_row(item, current, previous)
    text = FetchMorningData._format_market_markdown([row])
    assert row.get("unreliable") is True
    assert "行情异常，已忽略" in text
    assert "-12.85%" not in text
    assert "6643" not in text
    assert any("不写入早报" in rec.message for rec in caplog.records)

    stock = {"name": "特斯拉", "symbol": "TSLA", "market": "US"}
    allowed = FetchMorningData._build_row(
        stock,
        _bar("TSLA", "US", 115.0, datetime.now().date(), frequency="1m"),
        _bar("TSLA", "US", 100.0, datetime.now().date() - timedelta(days=1)),
    )
    assert allowed["missing"] is False
    assert allowed["change_pct"] == 15

    on_limit = FetchMorningData._build_row(
        item,
        _bar("^GSPC", "US", 108.0, datetime.now().date(), frequency="1m"),
        _bar("^GSPC", "US", 100.0, datetime.now().date() - timedelta(days=1)),
    )
    assert on_limit["missing"] is False
    assert f"{on_limit['change_pct']:+.2f}%" == "+8.00%"


def test_yf_failure_drops_frozen_index_and_keeps_stock_daily_change(caplog, monkeypatch):
    today = datetime.now().date()
    stale_day = today - timedelta(days=10)
    items = [
        {"name": "标普500", "symbol": "^GSPC", "market": "US"},
        {"name": "特斯拉", "symbol": "TSLA", "market": "US"},
    ]
    db_rows = [
        _bar("^GSPC", "US", 7623.68, stale_day),
        _bar("TSLA", "US", 250.0, stale_day),
    ]
    step = _step(items, db_rows)
    fetcher = USStockYfFetcher.__new__(USStockYfFetcher)
    fetcher._daily_cache = {}
    fetcher._yf_limiter = _Limiter()

    def _boom(tickers):
        raise RuntimeError("YFRateLimitError")

    async def _no_history(*args, **kwargs):
        raise AssertionError("已有本次行情昨收时不应再请求历史接口")

    fetcher._download_daily = _boom
    fetcher.fetch_historical_data = _no_history
    step.us_fetcher = fetcher

    async def _quotes(codes):
        assert codes == ["gb_$inx", "gb_tsla"]
        assert "int_sp500" not in codes
        assert "int_nasdaq" not in codes
        return {
            "gb_$inx": ["标普指数", "6643.70", "38.98", "0.59"],
            "gb_tsla": [
                "特斯拉", "403.8200", "1.00", f"{today.isoformat()} 09:30:13",
                "4.0100", "404.6600", "414.2300", "397.6100",
            ],
        }

    monkeypatch.setattr("fetchers.sina_quote.fetch_sina_quotes", _quotes)
    with caplog.at_level(logging.WARNING):
        text = asyncio.run(step._build_market_block())

    assert "无最新数据" in text
    assert "-12.85%" not in text
    assert "6643" not in text
    assert "标普500(^GSPC)" in text
    assert _pct(403.82, 399.81) in text
    assert _pct(403.82, 250.0) not in text
    assert any("新浪指数报价不可用" in rec.message for rec in caplog.records)


def test_ndx_fallback_uses_nasdaq100_quote(monkeypatch):
    today = datetime.now().date()
    items = [{"name": "纳斯达克", "symbol": "^NDX", "market": "US"}]
    step = _step(items, [_bar("^NDX", "US", 30000.0, today - timedelta(days=10))])
    fetcher = USStockYfFetcher.__new__(USStockYfFetcher)
    fetcher._daily_cache = {}
    fetcher._yf_limiter = _Limiter()

    def _boom(tickers):
        raise RuntimeError("YFRateLimitError")

    async def _no_history(*args, **kwargs):
        raise AssertionError("纳指应使用新浪报价自带的昨收")

    fetcher._download_daily = _boom
    fetcher.fetch_historical_data = _no_history
    step.us_fetcher = fetcher

    async def _quotes(codes):
        assert codes == ["gb_$ndx"]
        return {
            "gb_$ndx": [
                "纳斯达克100", "27989.8197", "-1.39", f"{today.isoformat()} 06:30:00",
                "-395.0255", "28561.1669", "28753.3931", "27967.4419",
            ],
        }

    monkeypatch.setattr("fetchers.sina_quote.fetch_sina_quotes", _quotes)
    text = asyncio.run(step._build_market_block())
    prev = 27989.8197 - (-395.0255)
    assert _pct(27989.8197, prev) in text
    assert _pct(27989.8197, 30000.0) not in text
    assert "int_nasdaq" not in text


def test_live_index_fallback_uses_quote_prev_not_stale_db(caplog, monkeypatch):
    today = datetime.now().date()
    items = [{"name": "标普500", "symbol": "^GSPC", "market": "US"}]
    step = _step(items, [_bar("^GSPC", "US", 7623.68, today - timedelta(days=10))])
    fetcher = USStockYfFetcher.__new__(USStockYfFetcher)
    fetcher._daily_cache = {}
    fetcher._yf_limiter = _Limiter()
    def _boom(tickers):
        raise RuntimeError("YFRateLimitError")

    fetcher._download_daily = _boom

    async def _no_history(*args, **kwargs):
        raise AssertionError("应使用新浪报价自带的昨收")

    fetcher.fetch_historical_data = _no_history
    step.us_fetcher = fetcher

    async def _quotes(codes):
        assert codes == ["gb_$inx"]
        return {
            "gb_$inx": [
                "标普500指数", "7541.3999", "-0.51", f"{today.isoformat()} 05:51:02",
                "-38.6700", "7610.8301", "7662.2300", "7539.3799",
            ],
        }

    monkeypatch.setattr("fetchers.sina_quote.fetch_sina_quotes", _quotes)
    with caplog.at_level(logging.WARNING):
        text = asyncio.run(step._build_market_block())

    assert _pct(7541.3999, 7580.0699) in text
    assert "-12.85%" not in text
    assert _pct(7541.3999, 7623.68) not in text
    assert any("日线停在" in rec.message and "^GSPC" in rec.message for rec in caplog.records)
    assert step.market_db.saved == []


def test_real_daily_cache_fills_a_stale_db():
    today = datetime.now().date()
    item = {"name": "标普500", "symbol": "^GSPC", "market": "US"}
    current = _bar("^GSPC", "US", 7580.07, today, frequency="1m")
    current.timestamp = datetime.now()
    cached = [
        _bar("^GSPC", "US", 7720.39, today - timedelta(days=4)),
        _bar("^GSPC", "US", 7580.07, today - timedelta(days=3)),
    ]
    step = _step([item], [_bar("^GSPC", "US", 7623.68, today - timedelta(days=10))])

    class _Fetcher:
        def cached_daily_bars(self, symbol, market, start_date, end_date):
            return cached

        async def fetch_historical_data(self, **kwargs):
            raise AssertionError("缓存里已有真实日线")

    step.us_fetcher = _Fetcher()

    async def _current(watchlist):
        return {("^GSPC", "US"): current}

    step._fetch_current_prices = _current
    text = asyncio.run(step._build_market_block())
    assert _pct(7580.07, 7720.39) in text
    assert [bar.close for bar in step.market_db.saved] == [7720.39, 7580.07]


def test_stale_ashare_history_is_refilled_before_the_percent():
    today = datetime.now().date()
    item = {"name": "上证指数", "symbol": "000001", "market": "SH"}
    current = _bar("000001", "SH", 3920.0, today, frequency="1m")
    current.timestamp = datetime.now()
    fresh = [
        _bar("000001", "SH", 3900.0, today - timedelta(days=2)),
        _bar("000001", "SH", 3920.0, today - timedelta(days=1)),
    ]
    step = _step([item], [_bar("000001", "SH", 4000.0, today - timedelta(days=7))])

    class _A:
        def __init__(self):
            self.calls = 0

        async def fetch_historical_data(self, **kwargs):
            self.calls += 1
            return fresh

    step.stock_fetcher = _A()

    async def _current(watchlist):
        return {("000001", "SH"): current}

    step._fetch_current_prices = _current
    text = asyncio.run(step._build_market_block())
    assert _pct(3920.0, 3900.0) in text
    assert _pct(3920.0, 4000.0) not in text
    assert step.stock_fetcher.calls == 1
    assert step.market_db.saved


def test_refetch_that_is_still_stale_does_not_publish_a_percent():
    today = datetime.now().date()
    item = {"name": "上证指数", "symbol": "000001", "market": "SH"}
    current = _bar("000001", "SH", 3920.0, today, frequency="1m")
    current.timestamp = datetime.now()
    stale = _bar("000001", "SH", 4000.0, today - timedelta(days=7))
    step = _step([item], [stale])

    class _A:
        async def fetch_historical_data(self, **kwargs):
            return [stale]

    step.stock_fetcher = _A()

    async def _current(watchlist):
        return {("000001", "SH"): current}

    step._fetch_current_prices = _current
    text = asyncio.run(step._build_market_block())
    assert "无最新数据" in text
    assert _pct(3920.0, 4000.0) not in text
    assert "3920" not in text
