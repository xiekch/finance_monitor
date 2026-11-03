import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from steps.base import Step
from models.market import PriceData
from models.social import MorningData
from storage.market_db import MarketDataDB
from storage.social_store import SocialPostStore
from fetchers.astock_fetcher import AStockFetcher
from fetchers.us_stock_yf_fetcher import USStockYfFetcher
from fetchers.crypto_fetcher import CryptoFetcher
from fetchers.futures_fetcher import FuturesFetcher
from config.settings import API_CONFIG
from config.monitor import MONITOR_CONFIG
from config.morning_briefing import MORNING_BRIEFING_CONFIG
from utils.time_util import to_utc_iso, window_since


_GROUPS: List[Tuple[str, Tuple[str, ...]]] = [
    ("A 股", ("SH", "SZ")),
    ("港股", ("HK",)),
    ("美股", ("US", "NASDAQ", "NYSE")),
    ("日本", ("JP",)),
    ("韩国", ("KR",)),
    ("加密货币", ("CRYPTO",)),
    ("期货", ("FUT",)),
]

_A_STOCK_MARKETS = ("SH", "SZ")
_YFINANCE_MARKETS = ("US", "NASDAQ", "NYSE", "HK", "JP", "KR")
# 昨收最多早于行情日 5 天：覆盖周五收盘在下周二使用，以及往前再一根日线。
# 库里停在更早的日期时，涨跌幅会变成多日累计，不能写进早报。
_MAX_PREV_GAP_DAYS = 5
# 主要指数单日很少超过这个幅度。更大的数多半是冻结点位或昨收串了多日。
_INDEX_MOVE_LIMIT_PCT = 8.0
_MAJOR_INDEX_SYMBOLS = frozenset({
    "^GSPC", "^DJI", "^NDX", "^N225", "^KS11",
    "000001", "000300", "399001", "399006", "000688",
})


class FetchMorningData(Step):

    def __init__(self):
        self.name = "FetchMorningData"
        self.social_store = SocialPostStore()
        self.market_db = MarketDataDB()
        self.stock_fetcher = AStockFetcher(API_CONFIG)
        self.us_fetcher = USStockYfFetcher(API_CONFIG)
        self.crypto_fetcher = CryptoFetcher(API_CONFIG)
        self.futures_fetcher = FuturesFetcher(API_CONFIG)
        self.cfg = MORNING_BRIEFING_CONFIG

    async def process(self, items: list = ()) -> List[MorningData]:
        window_hours = self.cfg["window_hours"]
        since = window_since(window_hours)

        posts = self.social_store.get_posts_since(since)
        logging.info(
            f"[{self.name}] 读取到 {len(posts)} 条社交帖子 "
            f"(window={window_hours}h, since={to_utc_iso(since)})"
        )

        market_block = await self._build_market_block()

        if not posts and not market_block.strip():
            logging.warning(f"[{self.name}] 无社交帖子且无行情数据，跳过")
            return []

        return [MorningData(
            posts=posts,
            market_block=market_block,
            window_hours=window_hours,
        )]

    async def _build_market_block(self) -> str:
        watchlist = self._collect_watchlist()
        if not watchlist:
            return ""

        current_by_key = await self._fetch_current_prices(watchlist)

        rows: List[dict] = []
        for item in watchlist:
            key = (item["symbol"], item["market"])
            current = current_by_key.get(key)
            previous = await self._get_prev_close(item, current)
            rows.append(self._build_row(item, current, previous))

        return self._format_market_markdown(rows)

    def _collect_watchlist(self) -> List[dict]:
        seen: dict = {}
        for asset_list in MONITOR_CONFIG.values():
            for asset in asset_list:
                key = (asset["symbol"], asset.get("market", ""))
                if key in seen:
                    continue
                seen[key] = {
                    "name": asset.get("name", asset["symbol"]),
                    "symbol": asset["symbol"],
                    "market": asset.get("market", ""),
                }
        return list(seen.values())

    @staticmethod
    def _is_today(price: PriceData, today: Optional[date] = None) -> bool:
        """现价是否属于今天；没有今天数据则不展示旧行情。"""
        ref = today if today is not None else date.today()
        return price.timestamp.date() == ref

    async def _fetch_current_prices(
        self, watchlist: List[dict],
    ) -> Dict[Tuple[str, str], PriceData]:
        """批量拉现价：只要今天的数据。收盘后仍取新浪收盘价，再回落今天的分钟线或日线。"""
        today = date.today()
        grouped: Dict[str, List[dict]] = {
            "astock": [],
            "yf": [],
            "crypto": [],
            "fut": [],
        }
        for item in watchlist:
            market = item["market"]
            if market in _A_STOCK_MARKETS:
                grouped["astock"].append(item)
            elif market in _YFINANCE_MARKETS:
                grouped["yf"].append(item)
            elif market == "CRYPTO":
                grouped["crypto"].append(item)
            elif market == "FUT":
                grouped["fut"].append(item)

        results: Dict[Tuple[str, str], PriceData] = {}

        async def _merge(fetcher_coro, label: str):
            try:
                prices = await fetcher_coro
            except Exception as e:
                logging.error(f"[{self.name}] 拉取{label}现价失败: {e}")
                return
            for price in prices:
                if self._is_today(price, today):
                    results[(price.symbol, price.market)] = price

        if grouped["astock"]:
            await _merge(
                self.stock_fetcher.fetch_realtime_data(grouped["astock"]), "A股",
            )
        if grouped["yf"]:
            await _merge(
                self.us_fetcher.fetch_realtime_data(grouped["yf"]), "yfinance",
            )
        if grouped["crypto"]:
            await _merge(
                self.crypto_fetcher.fetch_realtime_data(grouped["crypto"]), "加密货币",
            )
        if grouped["fut"]:
            await _merge(
                self.futures_fetcher.fetch_realtime_data(grouped["fut"]), "期货",
            )

        for item in watchlist:
            key = (item["symbol"], item["market"])
            if key in results:
                continue
            latest_1m = self.market_db.get_latest_price(
                symbol=item["symbol"], market=item["market"], frequency="1m",
            )
            if latest_1m is not None and self._is_today(latest_1m, today):
                results[key] = latest_1m
                continue
            latest_1d = self.market_db.get_latest_price(
                symbol=item["symbol"], market=item["market"], frequency="1d",
            )
            if latest_1d is not None and self._is_today(latest_1d, today):
                results[key] = latest_1d

        return results

    @staticmethod
    def _pick_prev_close(
        rows: List[PriceData], before: date, current: Optional[PriceData] = None,
    ) -> Optional[PriceData]:
        """取现价上一交易日的收盘。

        同一天可能有多条记录，按 date 去重后取该日最后一条。
        最新一根的收盘若就是本次现价，那根是当前这笔行情，再往前一根才是昨收。
        """
        if not rows:
            return None

        by_date: dict = {}
        for row in rows:
            by_date[row.timestamp.date()] = row
        dates = sorted(by_date)
        if (
            current is not None
            and by_date[dates[-1]].close == current.close
            and len(dates) >= 2
        ):
            return by_date[dates[-2]]

        candidates = [d for d in dates if d < before]
        if not candidates:
            return None
        chosen = by_date[candidates[-1]]
        if current is not None and chosen.close == current.close:
            earlier = [d for d in candidates if d < chosen.timestamp.date()]
            if not earlier:
                return None
            return by_date[earlier[-1]]
        return chosen

    @staticmethod
    def _prev_is_recent(previous: Optional[PriceData], before: date) -> bool:
        if previous is None:
            return False
        gap = (before - previous.timestamp.date()).days
        return 0 <= gap <= _MAX_PREV_GAP_DAYS

    @staticmethod
    def _choose_prev(
        db_prev: Optional[PriceData],
        fresh_prev: Optional[PriceData],
        before: date,
    ) -> Optional[PriceData]:
        """过期的库内日线让位给本次行情里更近的昨收。同一天优先用本次行情。"""
        fresh_ok = FetchMorningData._prev_is_recent(fresh_prev, before)
        db_ok = FetchMorningData._prev_is_recent(db_prev, before)
        if fresh_ok and (
            not db_ok or fresh_prev.timestamp.date() >= db_prev.timestamp.date()
        ):
            return fresh_prev
        if db_ok:
            return db_prev
        if fresh_prev is None:
            return db_prev
        if db_prev is None or fresh_prev.timestamp.date() >= db_prev.timestamp.date():
            return fresh_prev
        return db_prev

    def _peek_fresh_daily(self, item: dict) -> Optional[List[PriceData]]:
        if item["market"] not in _YFINANCE_MARKETS:
            return None
        end = datetime.now()
        start = end - timedelta(days=14)
        return self.us_fetcher.cached_daily_bars(
            item["symbol"], item["market"], start, end,
        )

    def _store_daily_bars(self, bars: List[PriceData]) -> None:
        for bar in bars:
            if bar.frequency != "1d" or getattr(bar, "quote_fallback", False):
                continue
            self.market_db.save_price_data(bar)

    async def _get_prev_close(
        self, item: dict, current: Optional[PriceData],
    ) -> Optional[PriceData]:
        """现价上一交易日的收盘。停更多日的日线不能拿来算一日涨跌幅。"""
        if current is None:
            return None
        before = current.timestamp.date()
        symbol, market = item["symbol"], item["market"]
        end = datetime.now()
        start = end - timedelta(days=14)
        db_rows = self.market_db.get_historical_prices(
            symbol=symbol, market=market, frequency="1d",
            start_date=start, end_date=end,
        )
        db_prev = self._pick_prev_close(db_rows, before, current)
        cached_rows = self._peek_fresh_daily(item)
        fresh_prev = self._pick_prev_close(cached_rows or [], before, current)
        chosen = self._choose_prev(db_prev, fresh_prev, before)
        if self._prev_is_recent(chosen, before):
            self._maybe_store_fresher_daily(
                item, db_prev, chosen, fresh_prev, cached_rows, before,
            )
            return chosen

        if cached_rows is not None:
            self._log_missing_prev(symbol, market, chosen, before)
            return None

        self._log_refetch(symbol, market, chosen, before)
        fetched = await self._fetch_recent_daily(item)
        fetched_prev = self._pick_prev_close(fetched or [], before, current)
        if self._prev_is_recent(fetched_prev, before):
            self._store_daily_bars(fetched or [])
            logging.info(
                f"[{self.name}] {symbol}({market}) 已补上 "
                f"{fetched_prev.timestamp.date()} 日线，用作昨收"
            )
            return fetched_prev
        self._log_missing_prev(symbol, market, fetched_prev or chosen, before, after_fetch=True)
        return None

    def _maybe_store_fresher_daily(
        self,
        item: dict,
        db_prev: Optional[PriceData],
        chosen: PriceData,
        fresh_prev: Optional[PriceData],
        cached_rows: Optional[List[PriceData]],
        before: date,
    ) -> None:
        if chosen is not fresh_prev or not cached_rows:
            return
        if db_prev is not None and self._prev_is_recent(db_prev, before):
            return
        self._store_daily_bars(cached_rows)
        symbol, market = item["symbol"], item["market"]
        if db_prev is None:
            logging.info(
                f"[{self.name}] {symbol}({market}) 库内没有昨收，"
                f"改用本次行情 {chosen.timestamp.date()} 收盘价"
            )
            return
        gap = (before - db_prev.timestamp.date()).days
        logging.warning(
            f"[{self.name}] {symbol}({market}) 日线停在 {db_prev.timestamp.date()}，"
            f"距 {before} 已有 {gap} 天，改用 {chosen.timestamp.date()} 收盘价"
        )

    def _log_refetch(
        self, symbol: str, market: str, chosen: Optional[PriceData], before: date,
    ) -> None:
        if chosen is None:
            logging.warning(f"[{self.name}] {symbol}({market}) 没有可用昨收，尝试补拉")
            return
        gap = (before - chosen.timestamp.date()).days
        logging.warning(
            f"[{self.name}] {symbol}({market}) 日线停在 {chosen.timestamp.date()}，"
            f"距 {before} 已有 {gap} 天，尝试补拉"
        )

    def _log_missing_prev(
        self,
        symbol: str,
        market: str,
        chosen: Optional[PriceData],
        before: date,
        after_fetch: bool = False,
    ) -> None:
        if chosen is None:
            if after_fetch:
                message = f"[{self.name}] {symbol}({market}) 补拉后仍没有可用昨收，涨跌幅不写入早报"
            else:
                message = f"[{self.name}] {symbol}({market}) 没有可用昨收，涨跌幅不写入早报"
            logging.warning(message)
            return
        gap = (before - chosen.timestamp.date()).days
        if after_fetch:
            tail = "补拉后仍不能当作昨收，涨跌幅不写入早报"
        else:
            tail = "涨跌幅不写入早报"
        logging.warning(
            f"[{self.name}] {symbol}({market}) 日线停在 {chosen.timestamp.date()}，"
            f"距 {before} 已有 {gap} 天，{tail}"
        )

    async def _fetch_recent_daily(self, item: dict) -> Optional[List[PriceData]]:
        market, symbol = item["market"], item["symbol"]
        end = datetime.now()
        start = end - timedelta(days=10)
        try:
            if market in _A_STOCK_MARKETS:
                return await self.stock_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d", limit=7, market=market,
                )
            if market in _YFINANCE_MARKETS:
                return await self.us_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d", start_date=start, end_date=end,
                    market=market,
                )
            if market == "CRYPTO":
                return await self.crypto_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d", start_date=start, end_date=end,
                )
            if market == "FUT":
                return await self.futures_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d", limit=7, market="FUT",
                )
            return None
        except Exception as e:
            logging.error(f"[{self.name}] {symbol}({market}) fetch fallback 异常: {e}")
            return None

    @staticmethod
    def _build_row(
        item: dict, current: Optional[PriceData], previous: Optional[PriceData],
    ) -> dict:
        if current is None or previous is None or not previous.close:
            return {**item, "missing": True}
        change_pct = (current.close - previous.close) / previous.close * 100
        if item["symbol"] in _MAJOR_INDEX_SYMBOLS and abs(change_pct) > _INDEX_MOVE_LIMIT_PCT:
            logging.warning(
                f"[FetchMorningData] {item.get('name', item['symbol'])}({item['symbol']}) "
                f"日涨跌 {change_pct:+.2f}% 超过 {_INDEX_MOVE_LIMIT_PCT:.0f}%，不写入早报"
            )
            return {**item, "missing": True, "unreliable": True}
        return {**item, "missing": False, "current_price": current.close, "change_pct": change_pct}

    @staticmethod
    def _format_market_markdown(rows: List[dict]) -> str:
        grouped: dict = {label: [] for label, _ in _GROUPS}
        other: list = []
        for row in rows:
            placed = False
            for label, markets in _GROUPS:
                if row["market"] in markets:
                    grouped[label].append(row)
                    placed = True
                    break
            if not placed:
                other.append(row)
        if other:
            grouped["其他"] = other

        lines: list[str] = []
        for label, group_rows in grouped.items():
            if not group_rows:
                continue
            lines.append(f"【{label}】")
            for r in group_rows:
                if r.get("unreliable"):
                    lines.append(f"{r['name']}({r['symbol']}) 行情异常，已忽略")
                elif r["missing"]:
                    lines.append(f"{r['name']}({r['symbol']}) 无最新数据")
                else:
                    arrow = "📈" if r["change_pct"] >= 0 else "📉"
                    lines.append(
                        f"{arrow} {r['name']}({r['symbol']}) "
                        f"{r['current_price']:.4f} {r['change_pct']:+.2f}%"
                    )
            lines.append("")
        return "\n".join(lines)
