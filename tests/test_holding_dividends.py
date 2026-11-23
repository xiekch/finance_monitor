import asyncio
from datetime import date

import pandas as pd
import pytest

import fetchers.holding_dividends as hd
from analyzers.portfolio import Dividend
from models.holdings import Holding

SINCE = date(2026, 10, 23)


def _holding(symbol, market, since=SINCE):
    return Holding(symbol=symbol, market=market, name=symbol, quantity=100, cost=1, since=since)


def test_stock_frame_uses_per_10_shares_and_skips_unimplemented_plans():
    df = pd.DataFrame({
        "现金分红-现金分红比例": [280.2423, 5.0, None, 0.0],
        "除权除息日": ["2026-06-26", None, "2026-12-01", "2026-03-01"],
    })
    assert hd.stock_dividends_from_frame(df) == [Dividend(date(2026, 6, 26), pytest.approx(28.02423))]


def test_stock_frame_empty_or_unexpected_columns():
    assert hd.stock_dividends_from_frame(None) == []
    assert hd.stock_dividends_from_frame(pd.DataFrame()) == []
    assert hd.stock_dividends_from_frame(pd.DataFrame({"别的列": [1]})) == []


def test_fund_frame_differences_the_cumulative_total():
    df = pd.DataFrame({
        "日期": ["2026-07-15", "2026-04-16", "2026-10-22"],   # 乱序也要排好
        "累计分红": [0.033, 0.024, 0.044],
    })
    got = hd.fund_dividends_from_frame(df)
    assert [d.ex_date for d in got] == [date(2026, 4, 16), date(2026, 7, 15), date(2026, 10, 22)]
    assert [d.per_unit for d in got] == pytest.approx([0.024, 0.009, 0.011])
    assert hd.fund_dividends_from_frame(pd.DataFrame(columns=["日期", "累计分红"])) == []


def test_yf_series():
    series = pd.Series([0.27, 0.0], index=pd.to_datetime(["2026-11-12", "2026-08-10"]))
    assert hd.yf_dividends_from_series(series) == [Dividend(date(2026, 11, 12), 0.27)]
    assert hd.yf_dividends_from_series(pd.Series(dtype=float)) == []


def test_is_fund():
    assert hd.is_fund(_holding("518880", "SH")) and hd.is_fund(_holding("560610", "SH"))
    assert hd.is_fund(_holding("159605", "SZ")) and hd.is_fund(_holding("161725", "SZ"))
    assert not hd.is_fund(_holding("600519", "SH")) and not hd.is_fund(_holding("000333", "SZ"))
    assert not hd.is_fund(_holding("510", "HK"))


def test_fetch_picks_source_by_market_and_survives_failures(monkeypatch):
    calls = []

    def fake_fetch_one(h):
        calls.append(h.symbol)
        if h.symbol == "600519":
            raise RuntimeError("SSL")
        return [Dividend(date(2026, 11, 18), 0.5)]

    monkeypatch.setattr(hd, "_fetch_one", fake_fetch_one)
    holdings = [
        _holding("600519", "SH"),
        _holding("000333", "SZ"),
        _holding("00700", "HK", since=None),   # 没 since 不查
        _holding("BTCUSDT", "CRYPTO"),         # 没有分红不查
        _holding("CU0", "FUT"),
    ]
    got = asyncio.run(hd.fetch_holding_dividends(holdings, date(2026, 11, 23)))
    assert sorted(calls) == ["000333", "600519"]
    # 取失败的不在结果里，调用方才能区分「没有分红」和「没取到」
    assert got == {"000333": [Dividend(date(2026, 11, 18), 0.5)]}


def test_retry_recovers_from_transient_error(monkeypatch):
    monkeypatch.setattr(hd.time, "sleep", lambda _: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("SSLEOFError")
        return "ok"

    assert hd._retry(flaky) == "ok" and len(attempts) == 3

    def broken():
        raise OSError("down")

    with pytest.raises(RuntimeError, match="down"):
        hd._retry(broken)
