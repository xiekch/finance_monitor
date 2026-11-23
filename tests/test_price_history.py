from datetime import date

import pandas as pd
import pytest

from fetchers.price_history import DailyBar, bars_from_frame, fetch_daily_bars, yahoo_ticker


@pytest.mark.parametrize("symbol, expected", [
    ("512200", "512200.SS"),     # 沪市场内 ETF
    ("002594", "002594.SZ"),
    ("SH601857", "601857.SS"),   # 带前后缀的写法也认
    ("TLT", "TLT"),
    ("700.HK", "0700.HK"),
])
def test_yahoo_ticker_supported(symbol, expected):
    assert yahoo_ticker(symbol) == expected


@pytest.mark.parametrize("symbol", ["920001", "833533", "XAUUSD", "GCZ26", ""])  # 北交所、黄金、期货
def test_yahoo_ticker_unsupported(symbol):
    assert yahoo_ticker(symbol) is None


def _frame(rows):
    index = pd.DatetimeIndex([pd.Timestamp(d, tz="Asia/Shanghai") for d, *_ in rows])
    return pd.DataFrame(
        [dict(Open=o, High=h, Low=l, Close=c) for _, o, h, l, c in rows], index=index,
    )


def test_bars_from_frame_uses_local_trading_day_and_skips_nan():
    frame = _frame([
        ("2026-11-19", 1.075, 1.080, 1.053, 1.057),
        ("2026-11-20", 1.045, 1.050, 1.011, 1.011),
        ("2026-11-21", float("nan"), float("nan"), float("nan"), float("nan")),
    ])
    assert bars_from_frame(frame) == [
        DailyBar(date(2026, 11, 19), 1.075, 1.080, 1.053, 1.057),
        DailyBar(date(2026, 11, 20), 1.045, 1.050, 1.011, 1.011),
    ]
    assert bars_from_frame(None) == []
    assert bars_from_frame(pd.DataFrame()) == []


def test_fetch_daily_bars_filters_window_and_passes_yahoo_ticker():
    calls = []

    def history(ticker, start, end):
        calls.append((ticker, start, end))
        return _frame([
            ("2026-11-18", 1, 1, 1, 1),
            ("2026-11-19", 1.075, 1.080, 1.053, 1.057),
            ("2026-11-23", 1, 1, 1, 1),
        ])

    bars = fetch_daily_bars("512200", date(2026, 11, 19), date(2026, 11, 20), history_fn=history)
    assert [b.day for b in bars] == [date(2026, 11, 19)]
    assert calls == [("512200.SS", date(2026, 11, 19), date(2026, 11, 20))]


def test_fetch_daily_bars_unsupported_symbol_never_calls_network():
    def boom(*a, **k):
        raise AssertionError("不该调用")

    assert fetch_daily_bars("XAUUSD", date(2026, 11, 1), date(2026, 11, 2), history_fn=boom) is None


def test_fetch_daily_bars_retries_then_gives_up():
    attempts = []

    def flaky(ticker, start, end):
        attempts.append(ticker)
        raise RuntimeError("rate limited")

    sleeps = []
    assert fetch_daily_bars("TLT", date(2026, 11, 1), date(2026, 11, 2),
                            history_fn=flaky, sleep=sleeps.append) is None
    assert len(attempts) == 2 and sleeps == [1.0]

