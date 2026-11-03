"""新浪行情批量报价。A 股、指数和国内期货主力共用这一处，不需要 API key。"""
import asyncio
from datetime import date, datetime
from typing import Dict, List, Optional

import requests

from models.market import PriceData


_SINA_URL = "https://hq.sinajs.cn/list={codes}"
_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}

# int_dji / int_nasdaq / int_sp500 / int_nikkei 没有交易日，点位会长期停更
# （2026-11 仍见 int_sp500=6643.70）。早报只接受带日期的报价。
# ^NDX 是纳斯达克100，对应 gb_$ndx；int_nasdaq 和 gb_$ixic 是纳斯达克综合指数。
_INDEX_CODES = {
    "^DJI": "gb_$dji",
    "^NDX": "gb_$ndx",
    "^GSPC": "gb_$inx",
    "^N225": "b_NKY",
    "^KS11": "b_KOSPI",
}
_US_INDEX_SYMBOLS = frozenset({"^DJI", "^NDX", "^GSPC"})
_ASIA_INDEX_SYMBOLS = frozenset({"^N225", "^KS11"})
INDEX_SYMBOLS = frozenset(_INDEX_CODES)
# 周五报价放到下周二仍可用；再早视为冻结，不能当今天的现价。
_MAX_QUOTE_AGE_DAYS = 4


def overseas_sina_code(symbol: str, market: str) -> Optional[str]:
    """港股、美股和日韩指数的新浪代码。yfinance 被限流时用作备用。"""
    if symbol in _INDEX_CODES:
        return _INDEX_CODES[symbol]
    market = (market or "").upper()
    if market == "HK":
        return "hk" + symbol.zfill(5)
    if market in ("US", "NASDAQ", "NYSE"):
        return "gb_" + symbol.lower()
    return None


def quote_session_date(
    symbol: str, market: str, fields: Optional[List[str]],
) -> Optional[date]:
    """报价里的交易日。没有日期的指数接口不能用来判断新旧。"""
    if not fields:
        return None
    if symbol in _US_INDEX_SYMBOLS or (market or "").upper() in ("US", "NASDAQ", "NYSE"):
        return _field_date(fields, 3)
    if symbol in _ASIA_INDEX_SYMBOLS:
        return _field_date(fields, 6)
    return None


def overseas_quote(
    symbol: str, market: str, fields: Optional[List[str]], today: Optional[date] = None,
) -> Optional[tuple]:
    """返回 (现价 PriceData, 昨收)。字段布局按市场不同。

    美股和指数必须带近期交易日。int_* 那种只有名称、点位、涨跌的报价直接丢掉。
    """
    if not fields:
        return None
    today = today or date.today()
    market = (market or "").upper()
    if symbol in _US_INDEX_SYMBOLS:
        parsed = _dated_us_ohlc(fields, today)
    elif symbol in _ASIA_INDEX_SYMBOLS:
        parsed = _dated_asia_index_ohlc(fields, today)
    elif market == "HK":
        parsed = _hk_ohlc(fields)
    elif market in ("US", "NASDAQ", "NYSE"):
        parsed = _dated_us_ohlc(fields, today)
    else:
        return None
    if parsed is None:
        return None
    close, prev, open_, high, low = parsed
    price = PriceData(
        symbol=symbol,
        market=market if symbol not in _INDEX_CODES else _index_market(symbol, market),
        timestamp=datetime.now(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=0,
        frequency="1m",
    )
    return price, prev


def _index_market(symbol: str, market: str) -> str:
    if symbol == "^N225":
        return "JP"
    if symbol == "^KS11":
        return "KR"
    return market or "US"


def sina_code(symbol: str, market: str) -> str:
    market = (market or "").upper()
    if market in ("SH", "SZ"):
        return f"{market.lower()}{symbol}"
    if market == "FUT":
        return f"nf_{symbol}"
    raise ValueError(f"新浪行情不支持的市场: {market} {symbol}")


def parse_sina_body(text: str) -> Dict[str, List[str]]:
    """把 hq.sinajs.cn 的 JS 赋值解析成 code -> 字段列表。空报价不收录。"""
    parsed: Dict[str, List[str]] = {}
    for line in text.split(";"):
        line = line.strip()
        if "hq_str_" not in line or "=" not in line:
            continue
        left, right = line.split("=", 1)
        code = left.split("hq_str_", 1)[-1].strip()
        payload = right.strip().strip('"').strip()
        if not code or not payload:
            continue
        parsed[code] = payload.split(",")
    return parsed


def price_from_fields(symbol: str, market: str, fields: List[str]) -> Optional[PriceData]:
    market = (market or "").upper()
    if market in ("SH", "SZ"):
        return _ashare_price(symbol, market, fields)
    if market == "FUT":
        return _futures_price(symbol, market, fields)
    return None


def _ashare_price(symbol: str, market: str, fields: List[str]) -> Optional[PriceData]:
    # 0 名称, 1 开盘, 2 昨收, 3 现价, 4 最高, 5 最低, 8 成交量
    if len(fields) < 9:
        return None
    close = _num(fields[3])
    if close <= 0:
        return None
    return PriceData(
        symbol=symbol,
        market=market,
        timestamp=datetime.now(),
        open=_num(fields[1]),
        high=_num(fields[4]),
        low=_num(fields[5]),
        close=close,
        volume=_num(fields[8]),
        frequency="1m",
    )


def _futures_price(symbol: str, market: str, fields: List[str]) -> Optional[PriceData]:
    # 2 开盘, 3 最高, 4 最低, 8 最新价, 14 成交量。昨收在字段 5，白盘经常是 0，
    # 昨结算在字段 10；涨跌幅由早报自己用日线昨收计算，这里只提供现价。
    if len(fields) < 15:
        return None
    close = _num(fields[8])
    if close <= 0:
        return None
    return PriceData(
        symbol=symbol,
        market=market,
        timestamp=datetime.now(),
        open=_num(fields[2]),
        high=_num(fields[3]),
        low=_num(fields[4]),
        close=close,
        volume=_num(fields[14]),
        frequency="1m",
    )


def _hk_ohlc(fields: List[str]) -> Optional[tuple]:
    # 2 开盘, 3 昨收, 4 最高, 5 最低, 6 现价
    if len(fields) < 7:
        return None
    close = _num(fields[6])
    prev = _num(fields[3])
    if close <= 0 or prev <= 0:
        return None
    return close, prev, _num(fields[2]), _num(fields[4]), _num(fields[5])


def _us_ohlc(fields: List[str]) -> Optional[tuple]:
    # 1 现价, 4 涨跌额, 5 开盘, 6 最高, 7 最低
    if len(fields) < 8:
        return None
    close = _num(fields[1])
    change = _num(fields[4])
    prev = close - change
    if close <= 0 or prev <= 0:
        return None
    return close, prev, _num(fields[5]), _num(fields[6]), _num(fields[7])


def _dated_us_ohlc(fields: List[str], today: date) -> Optional[tuple]:
    if not _session_is_recent(_field_date(fields, 3), today):
        return None
    return _us_ohlc(fields)


def _dated_asia_index_ohlc(fields: List[str], today: date) -> Optional[tuple]:
    # b_NKY / b_KOSPI：1 现价，2 涨跌额，6 交易日。没有交易日的 int_* 四字段报价在这里被丢掉。
    if not _session_is_recent(_field_date(fields, 6), today):
        return None
    return _index_ohlc(fields)


def _index_ohlc(fields: List[str]) -> Optional[tuple]:
    # 1 现价, 2 涨跌额。开高低用现价占位，早报只取收盘和昨收。
    if len(fields) < 3:
        return None
    close = _num(fields[1])
    change = _num(fields[2])
    prev = close - change
    if close <= 0 or prev <= 0:
        return None
    return close, prev, close, close, close


def _field_date(fields: List[str], index: int) -> Optional[date]:
    if len(fields) <= index:
        return None
    return _parse_date(fields[index])


def _parse_date(value: str) -> Optional[date]:
    text = (value or "").strip()
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _session_is_recent(session: Optional[date], today: date) -> bool:
    if session is None:
        return False
    delta = (today - session).days
    return -1 <= delta <= _MAX_QUOTE_AGE_DAYS


def _num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def fetch_sina_quotes(codes: List[str]) -> Dict[str, List[str]]:
    if not codes:
        return {}
    url = _SINA_URL.format(codes=",".join(codes))

    def _get() -> str:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = "gbk"
        return resp.text

    text = await asyncio.to_thread(_get)
    return parse_sina_body(text)
