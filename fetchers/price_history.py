"""投资建议用的历史日 K：只取事实，不做判断。

数据源是 Yahoo Finance，价格不复权（建议里的目标价、失效价都是当时盘面上的价格）。
支持 A 股（沪深，含场内 ETF）、美股 ticker、港股；北交所、现货黄金、期货取不到，
返回 None，调用方按「没有程序行情」处理，回落到让模型自己联网查。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, List, Optional

from models.advice import normalize_symbol

_A_SHARE = re.compile(r"^\d{6}$")
_HK = re.compile(r"^\d{1,5}\.HK$")
_US = re.compile(r"^[A-Z]{1,5}$")
# 920xxx 是北交所新代码，4、8 开头也是北交所；Yahoo 都查不到
_NOT_COVERED_PREFIXES = ("920", "4", "8")
DATA_SOURCE = "Yahoo Finance 日 K（未复权）"
_ATTEMPTS = 2


@dataclass(frozen=True)
class DailyBar:
    day: date
    open: float
    high: float
    low: float
    close: float


def yahoo_ticker(symbol: str) -> Optional[str]:
    """建议里的 symbol 转 Yahoo ticker；不支持的返回 None。"""
    s = normalize_symbol(symbol or "")
    if _A_SHARE.match(s):
        if s.startswith(_NOT_COVERED_PREFIXES):
            return None
        if s[0] in "569":
            return f"{s}.SS"
        if s[0] in "0123":
            return f"{s}.SZ"
        return None
    if _HK.match(s):
        return f"{int(s.split('.')[0]):04d}.HK"
    if _US.match(s):
        return s
    return None


def bars_from_frame(frame) -> List[DailyBar]:
    """yfinance 的日线表转 DailyBar。索引是交易所本地午夜，取日期部分即交易日。"""
    bars: List[DailyBar] = []
    if frame is None or getattr(frame, "empty", True):
        return bars
    for stamp, row in frame.iterrows():
        try:
            values = [float(row[k]) for k in ("Open", "High", "Low", "Close")]
        except (KeyError, TypeError, ValueError):
            continue
        if any(v != v for v in values):  # NaN
            continue
        day = stamp.date() if hasattr(stamp, "date") else stamp
        bars.append(DailyBar(day, *values))
    return sorted(bars, key=lambda b: b.day)


def _yahoo_history(ticker: str, start: date, end: date):
    import yfinance as yf

    return yf.Ticker(ticker).history(
        start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=False,
    )


def fetch_daily_bars(symbol: str, start: date, end: date,
                     history_fn: Callable = _yahoo_history,
                     sleep: Callable[[float], None] = time.sleep) -> Optional[List[DailyBar]]:
    """start 到 end（含）的日 K。不支持的标的或接口连续失败返回 None；没有交易日返回空列表。"""
    ticker = yahoo_ticker(symbol)
    if ticker is None:
        logging.info(f"[price_history] {symbol} 不在程序行情覆盖范围内")
        return None
    last_error: Optional[Exception] = None
    for attempt in range(_ATTEMPTS):
        try:
            frame = history_fn(ticker, start, end)
            return [b for b in bars_from_frame(frame) if start <= b.day <= end]
        except Exception as e:
            last_error = e
            if attempt + 1 < _ATTEMPTS:
                sleep(1.0)
    logging.warning(f"[price_history] {symbol}({ticker}) 取日 K 失败：{last_error}")
    return None
