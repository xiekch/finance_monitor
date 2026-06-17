import logging
from datetime import datetime
from typing import Any, List, Optional, Tuple

from steps.base import Step
from models.market import PriceData
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
    ("加密货币", ("CRYPTO",)),
    ("期货", ("FUT",)),
]

_A_STOCK_MARKETS = ("SH", "SZ")
_US_MARKETS = ("US", "NASDAQ", "NYSE")


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

    async def process(self, data: Any = None) -> dict | None:
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
            return None

        return {
            "posts": posts,
            "market_block": market_block,
            "window_hours": window_hours,
        }

    async def _build_market_block(self) -> str:
        watchlist = self._collect_watchlist()
        if not watchlist:
            return ""

        rows: List[dict] = []
        for item in watchlist:
            current, previous = await self._get_two_daily_closes(item)
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

    async def _get_two_daily_closes(
        self, item: dict,
    ) -> Tuple[Optional[PriceData], Optional[PriceData]]:
        symbol, market = item["symbol"], item["market"]
        end = datetime.now()
        start = end - timedelta(days=14)
        db_rows = self.market_db.get_historical_prices(
            symbol=symbol, market=market, frequency="1d",
            start_date=start, end_date=end,
        )
        if len(db_rows) >= 2:
            return db_rows[-1], db_rows[-2]

        fetched = await self._fetch_recent_daily(item)
        if not fetched or len(fetched) < 2:
            return None, None

        for d in fetched:
            self.market_db.save_price_data(d)
        return fetched[-1], fetched[-2]

    async def _fetch_recent_daily(self, item: dict) -> Optional[List[PriceData]]:
        market, symbol = item["market"], item["symbol"]
        end = datetime.now()
        start = end - timedelta(days=10)
        try:
            if market in _A_STOCK_MARKETS:
                return await self.stock_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d", limit=7, market=market,
                )
            if market in _US_MARKETS:
                return await self.us_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d", start_date=start, end_date=end,
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
                    lines.append(f"{r['name']}({r['symbol']}) 暂无数据")
                else:
                    arrow = "📈" if r["change_pct"] >= 0 else "📉"
                    lines.append(
                        f"{arrow} {r['name']}({r['symbol']}) "
                        f"{r['current_price']:.4f} {r['change_pct']:+.2f}%"
                    )
            lines.append("")
        return "\n".join(lines)
