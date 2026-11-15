"""持仓现价。A 股、港股、美股、国内期货走新浪，加密货币走币安。只取最新价和交易日。"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import requests

from analyzers.portfolio import PriceQuote
from config.holdings import MAX_PRICE_AGE_DAYS
from config.settings import API_CONFIG
from fetchers.sina_quote import fetch_sina_quotes
from models.holdings import Holding

SINA_SOURCE = "新浪行情"
BINANCE_SOURCE = "币安"

# 市场 -> (现价字段, 现价为 0 时的备用字段, 交易日字段)。备用字段是昨收：
# A 股集合竞价、港股开盘前现价是 0。
_LAYOUTS = {
    "SH": (3, 2, 30),
    "SZ": (3, 2, 30),
    "HK": (6, 3, 17),
    "US": (1, None, 3),
    "FUT": (8, None, 17),
}
# 美股报价的字段 3 是新浪更新时间（北京时间），收盘后会比交易日晚一天。
# 字段 25 是美东收盘时间（Nov 13 04:00PM EST），字段 29 是年份。
_US_SESSION, _US_YEAR = 25, 29
_QUOTE_ASSETS = ("USDT", "USDC", "USD")
_ATTEMPTS = 3


def sina_code_for(holding: Holding) -> Optional[str]:
    market, symbol = holding.market, holding.symbol.strip()
    if market in ("SH", "SZ"):
        return f"{market.lower()}{symbol}"
    if market == "HK":
        return "hk" + symbol.zfill(5)
    if market == "US":
        return "gb_" + symbol.lower()
    if market == "FUT":
        return "nf_" + symbol.upper()
    return None


def crypto_pair(symbol: str) -> str:
    """币安交易对。BTC、BTC-USD、BTCUSDT 都按 USDT 计价，和配置里的美元成本对应。"""
    s = symbol.strip().upper().replace("-", "").replace("/", "")
    for quote in _QUOTE_ASSETS:
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)] + "USDT"
    return s + "USDT"


def quote_from_fields(
    market: str, fields: Optional[List[str]], today: date,
) -> Optional[PriceQuote]:
    """从新浪报价字段里取现价和交易日。没有日期或日期太旧的报价不用。"""
    layout = _LAYOUTS.get(market)
    if layout is None or not fields:
        return None
    price_at, fallback_at, date_at = layout
    if len(fields) <= max(price_at, date_at):
        return None
    price = _num(fields[price_at])
    if price <= 0 and fallback_at is not None:
        price = _num(fields[fallback_at])
    if price <= 0:
        return None
    day = (_us_session(fields) if market == "US" else None) or _to_date(fields[date_at])
    if day is None or not -1 <= (today - day).days <= MAX_PRICE_AGE_DAYS:
        return None
    return PriceQuote(price=price, day=day, source=SINA_SOURCE)


async def fetch_holding_quotes(
    holdings: Iterable[Holding], today: Optional[date] = None,
) -> Dict[str, PriceQuote]:
    """以持仓的 symbol 为键。取不到的持仓不在结果里，不抛异常。"""
    today = today or date.today()
    holdings = list(holdings)
    codes = {h.symbol: code for h in holdings if (code := sina_code_for(h))}
    fields: Dict[str, List[str]] = {}
    if codes:
        try:
            fields = await fetch_sina_quotes(list(codes.values()))
        except Exception as e:
            logging.error(f"[holding_quotes] 新浪行情取不到: {e}")

    quotes: Dict[str, PriceQuote] = {}
    for h in holdings:
        if h.symbol in codes:
            quote = quote_from_fields(h.market, fields.get(codes[h.symbol]), today)
        elif h.market == "CRYPTO":
            quote = await _crypto_quote(h.symbol, today)
        else:
            quote = None
        if quote is None:
            logging.warning(f"[holding_quotes] {h.symbol} {h.name} 没有取到现价")
        else:
            quotes[h.symbol] = quote
    return quotes


async def _crypto_quote(symbol: str, today: date) -> Optional[PriceQuote]:
    try:
        price = await asyncio.to_thread(_binance_price, crypto_pair(symbol))
    except Exception as e:
        logging.error(f"[holding_quotes] 币安取不到 {symbol}: {e}")
        return None
    if price <= 0:
        return None
    # 加密货币全天交易，最新价就是今天的。
    return PriceQuote(price=price, day=today, source=BINANCE_SOURCE)


def _binance_price(pair: str) -> float:
    url = f"{API_CONFIG['binance']['base_url']}/api/v3/ticker/price"
    last: Optional[Exception] = None
    for attempt in range(_ATTEMPTS):
        try:
            resp = requests.get(url, params={"symbol": pair}, timeout=10)
            resp.raise_for_status()
            return float(resp.json()["price"])
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            last = e
            if attempt < _ATTEMPTS - 1:
                time.sleep(1)
    raise RuntimeError(f"{pair}: {last}")


def _us_session(fields: List[str]) -> Optional[date]:
    if len(fields) <= _US_YEAR:
        return None
    stamp = " ".join(fields[_US_SESSION].split()[:2])   # Nov 13
    try:
        return datetime.strptime(f"{stamp} {fields[_US_YEAR].strip()}", "%b %d %Y").date()
    except ValueError:
        return None


def _to_date(value: str) -> Optional[date]:
    text = (value or "").strip()[:10].replace("/", "-")
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
