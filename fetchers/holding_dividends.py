"""持仓的现金分红记录。A 股个股走东方财富，沪深 ETF 走新浪，港股和美股走雅虎财经。

只取有 since（持有起始日）的持仓。取不到的持仓不在结果里，由调用方当作「分红未知」，
不能当成「没有分红」。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, TypeVar

import pandas as pd

from analyzers.portfolio import Dividend
from config.holdings import DIVIDEND_ATTEMPTS, NO_DIVIDEND_MARKETS
from models.holdings import Holding

T = TypeVar("T")

# 东方财富「分红送配」表：现金分红比例是每 10 股派息（税前），没实施的方案没有除权除息日。
_EM_RATIO = "现金分红-现金分红比例"
_EM_EX_DATE = "除权除息日"
_EM_PER_SHARES = 10
# 新浪 ETF 分红表：累计每份分红，要自己做差。
_SINA_DATE, _SINA_TOTAL = "日期", "累计分红"


def is_fund(holding: Holding) -> bool:
    """沪深场内基金：沪市 5 开头（ETF、LOF），深市 15、16 开头。"""
    symbol = holding.symbol.strip()
    return (holding.market == "SH" and symbol.startswith("5")) or (
        holding.market == "SZ" and symbol.startswith(("15", "16"))
    )


def stock_dividends_from_frame(df: Optional[pd.DataFrame]) -> List[Dividend]:
    if df is None or df.empty or _EM_RATIO not in df or _EM_EX_DATE not in df:
        return []
    ratio = pd.to_numeric(df[_EM_RATIO], errors="coerce")
    ex_date = pd.to_datetime(df[_EM_EX_DATE], errors="coerce")
    return [
        Dividend(ex.date(), float(r) / _EM_PER_SHARES)
        for r, ex in zip(ratio, ex_date)
        if pd.notna(r) and pd.notna(ex) and r > 0
    ]


def fund_dividends_from_frame(df: Optional[pd.DataFrame]) -> List[Dividend]:
    if df is None or df.empty or _SINA_DATE not in df or _SINA_TOTAL not in df:
        return []
    frame = pd.DataFrame({
        "day": pd.to_datetime(df[_SINA_DATE], errors="coerce"),
        "total": pd.to_numeric(df[_SINA_TOTAL], errors="coerce"),
    }).dropna().sort_values("day")
    result: List[Dividend] = []
    previous = 0.0
    for day, total in zip(frame["day"], frame["total"]):
        if total > previous:
            result.append(Dividend(day.date(), float(total) - previous))
        previous = float(total)
    return result


def yf_dividends_from_series(series: Optional[pd.Series]) -> List[Dividend]:
    if series is None or len(series) == 0:
        return []
    return [Dividend(ts.date(), float(v)) for ts, v in series.items() if v and v > 0]


def _retry(fn: Callable[[], T]) -> T:
    """新浪、东方财富偶发 SSL 断开，重试一般就好。"""
    last: Optional[Exception] = None
    for attempt in range(DIVIDEND_ATTEMPTS):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 第三方库抛什么的都有
            last = e
            if attempt < DIVIDEND_ATTEMPTS - 1:
                time.sleep(1)
    raise RuntimeError(str(last)) from last


def _fetch_one(holding: Holding) -> List[Dividend]:
    symbol = holding.symbol.strip()
    if holding.market in ("SH", "SZ"):
        import akshare as ak
        if is_fund(holding):
            code = f"{holding.market.lower()}{symbol}"
            return fund_dividends_from_frame(_retry(lambda: ak.fund_etf_dividend_sina(symbol=code)))
        return stock_dividends_from_frame(_retry(lambda: ak.stock_fhps_detail_em(symbol=symbol)))
    if holding.market in ("HK", "US"):
        import yfinance as yf
        ticker = f"{int(symbol):04d}.HK" if holding.market == "HK" else symbol.replace(".", "-")
        return yf_dividends_from_series(_retry(lambda: _yf_dividends(yf, ticker)))
    return []


def _yf_dividends(yf: Any, ticker: str) -> pd.Series:
    series = yf.Ticker(ticker).dividends
    if getattr(series.index, "tz", None) is not None:
        series = series.tz_localize(None)
    return series


async def fetch_holding_dividends(
    holdings: Iterable[Holding], today: Optional[date] = None,
) -> Dict[str, List[Dividend]]:
    """以持仓的 symbol 为键，值是全部历史分红（按持有期过滤交给估值）。取不到的不在结果里。"""
    targets = [
        h for h in holdings if h.since is not None and h.market not in NO_DIVIDEND_MARKETS
    ]
    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch_one, h) for h in targets), return_exceptions=True)
    dividends: Dict[str, List[Dividend]] = {}
    for h, result in zip(targets, results):
        if isinstance(result, BaseException):
            logging.error(f"[holding_dividends] {h.symbol} {h.name} 取不到分红: {result}")
        else:
            dividends[h.symbol] = result
    return dividends
