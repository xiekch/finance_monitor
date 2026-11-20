"""A 股新股上市日历。数据来自 akshare 的东方财富「新股申购与中签」表，覆盖沪、深、北三个交易所。"""
import asyncio
import logging
import time
from datetime import date
from typing import Any, List, Optional

from models.market import NewStockListing

_FETCH_ATTEMPTS = 3
_RETRY_SLEEP_SECONDS = 3


def fetch_ipo_table() -> Any:
    """拉取全部新股表。接口偶尔超时，重试几次再放弃；最后一次的异常原样抛出。"""
    import akshare as ak

    for attempts_left in range(_FETCH_ATTEMPTS - 1, -1, -1):
        try:
            return ak.stock_xgsglb_em(symbol="全部股票")
        except Exception as e:
            if not attempts_left:
                raise
            logging.warning(f"[NewStockFetcher] 拉取新股表失败，{_RETRY_SLEEP_SECONDS}s 后重试: {e}")
            time.sleep(_RETRY_SLEEP_SECONDS)


async def fetch_listings_on(day: date) -> List[NewStockListing]:
    table = await asyncio.to_thread(fetch_ipo_table)
    return listings_on(table, day)


def listings_on(table: Any, day: date) -> List[NewStockListing]:
    """表里上市日期等于 ``day`` 的新股，按代码排序。"""
    if table is None or len(table) == 0:
        return []
    result: List[NewStockListing] = []
    for _, row in table.iterrows():
        if _to_date(row.get("上市日期")) != day:
            continue
        symbol = str(row.get("股票代码") or "").strip()
        if not symbol:
            continue
        result.append(NewStockListing(
            symbol=symbol,
            name=str(row.get("股票简称") or "").strip(),
            exchange=_short_exchange(row.get("交易所")),
            board=str(row.get("板块") or "").strip(),
            listing_date=day,
            issue_price=_to_float(row.get("发行价格")),
            issue_pe=_to_float(row.get("发行市盈率")),
            industry_pe=_to_float(row.get("行业市盈率")),
            issue_shares=_to_float(row.get("发行总数")),
            subscribe_date=_to_date(row.get("申购日期")),
        ))
    result.sort(key=lambda s: s.symbol)
    return result


def _short_exchange(value: Any) -> str:
    text = str(value or "").strip()
    for full, short in (("上海证券交易所", "上交所"), ("深圳证券交易所", "深交所"), ("北京证券交易所", "北交所")):
        if text == full:
            return short
    return text


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number
