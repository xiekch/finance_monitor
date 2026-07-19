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
        """批量拉现价：只要今天的数据；实时优先，再回落今天的 DB 分钟/日线。"""
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
        rows: List[PriceData], before: date,
    ) -> Optional[PriceData]:
        """取严格早于 before 的最近一根日线，作为昨收。

        同一天可能有多条记录，按 date 去重后取该日最后一条。
        """
        if not rows:
            return None

        by_date: dict = {}
        for row in rows:
            by_date[row.timestamp.date()] = row

        candidates = [d for d in sorted(by_date.keys()) if d < before]
        if not candidates:
            return None
        return by_date[candidates[-1]]

    async def _get_prev_close(
        self, item: dict, current: Optional[PriceData],
    ) -> Optional[PriceData]:
        """现价对应的昨收：严格早于现价日期（或今天）的最近日线收盘价。"""
        before = current.timestamp.date() if current is not None else date.today()
        symbol, market = item["symbol"], item["market"]
        end = datetime.now()
        start = end - timedelta(days=14)
        db_rows = self.market_db.get_historical_prices(
            symbol=symbol, market=market, frequency="1d",
            start_date=start, end_date=end,
        )
        previous = self._pick_prev_close(db_rows, before)
        if previous is not None:
            return previous

        fetched = await self._fetch_recent_daily(item)
        if not fetched:
            return None

        for d in fetched:
            self.market_db.save_price_data(d)
        return self._pick_prev_close(fetched, before)

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
                if r["missing"]:
                    lines.append(f"{r['name']}({r['symbol']}) 无最新数据")
                else:
                    arrow = "📈" if r["change_pct"] >= 0 else "📉"
                    lines.append(
                        f"{arrow} {r['name']}({r['symbol']}) "
                        f"{r['current_price']:.4f} {r['change_pct']:+.2f}%"
                    )
            lines.append("")
        return "\n".join(lines)
