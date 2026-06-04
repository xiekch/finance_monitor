import logging
from datetime import datetime, timedelta
from typing import Sequence, List, Optional, Tuple

from apscheduler.triggers.base import BaseTrigger

from producers.base_producer import BaseProducer
from models.messages import BaseMessage, MarketBriefingMessage
from models.market import PriceData
from storage.market_db import MarketDataDB
from fetchers.us_stock_yf_fetcher import USStockYfFetcher
from fetchers.crypto_fetcher import CryptoFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG


# 行情早报里展示用的市场分组与顺序。未列出的 market 走 "其他"。
_GROUPS: List[Tuple[str, Tuple[str, ...]]] = [
    ("A 股", ("SH", "SZ")),
    ("港股", ("HK",)),
    ("美股", ("US", "NASDAQ", "NYSE")),
    ("加密货币", ("CRYPTO",)),
    ("期货", ("FUT",)),
]

_US_MARKETS = ("US", "NASDAQ", "NYSE")


class MarketBriefingProducer(BaseProducer):
    """每日早报 producer：三频去重合集 → 最近两条 daily K → markdown 推送。

    数据策略：DB 优先，缺数据时回落 yfinance(美股)/Binance(crypto)；
    其他市场（A 股/港股/期货）无 fetcher fallback，缺数据则标记 "暂无"。
    """

    def __init__(
        self,
        trigger: Optional[BaseTrigger] = None,
        run_immediately: bool = False,
        ignore_schedule: bool = False,
    ):
        super().__init__(
            "MarketBriefingProducer",
            trigger=trigger,
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
        )
        self.db = MarketDataDB()
        self.us_fetcher = USStockYfFetcher(API_CONFIG)
        self.crypto_fetcher = CryptoFetcher(API_CONFIG)

    async def produce_data(self) -> Sequence[BaseMessage]:
        watchlist = self._collect_watchlist()
        if not watchlist:
            logging.warning(f"[{self.producer_name}] watchlist 为空，跳过早报")
            return []

        rows: List[dict] = []
        for item in watchlist:
            current, previous = await self._get_two_daily_closes(item)
            rows.append(self._build_row(item, current, previous))

        markdown = self._format_markdown(rows)
        hit = sum(1 for r in rows if not r["missing"])
        logging.info(
            f"[{self.producer_name}] 早报组装完成: {hit}/{len(rows)} 命中数据"
        )

        payload = {
            "markdown": markdown,
            "created_at": datetime.now().isoformat(),
            "row_count": len(rows),
            "hit_count": hit,
        }
        return [MarketBriefingMessage(payload=payload, source=self.producer_name)]

    def _collect_watchlist(self) -> List[dict]:
        """合并 minute/daily/weekly 三频的所有 asset，按 (symbol, market) 去重。"""
        seen: dict = {}
        for frequency in ("minute", "daily", "weekly"):
            asset_types = MONITOR_CONFIG.get(frequency, {})
            for asset_list in asset_types.values():
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
        self, item: dict
    ) -> Tuple[Optional[PriceData], Optional[PriceData]]:
        """返回 (current, previous) 两条 daily K 线；不足两条则 (None, None)。

        先查 MarketDataDB，命中即返回；否则按 market 选 fetcher 回落，并把
        拉到的历史顺手写回 DB，下次直接命中。
        """
        symbol = item["symbol"]
        market = item["market"]

        end = datetime.now()
        start = end - timedelta(days=14)
        db_rows = self.db.get_historical_prices(
            symbol=symbol, market=market, frequency="1d",
            start_date=start, end_date=end,
        )
        if len(db_rows) >= 2:
            return db_rows[-1], db_rows[-2]

        fetched = await self._fetch_recent_daily(item)
        if not fetched or len(fetched) < 2:
            logging.warning(
                f"[{self.producer_name}] {symbol}({market}) "
                f"DB={len(db_rows)} fetch={len(fetched) if fetched else 0}，"
                f"无法计算日涨跌"
            )
            return None, None

        for d in fetched:
            self.db.save_price_data(d)
        return fetched[-1], fetched[-2]

    async def _fetch_recent_daily(self, item: dict) -> Optional[List[PriceData]]:
        market = item["market"]
        symbol = item["symbol"]
        end = datetime.now()
        start = end - timedelta(days=10)
        try:
            if market in _US_MARKETS:
                return await self.us_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d",
                    start_date=start, end_date=end,
                )
            if market == "CRYPTO":
                return await self.crypto_fetcher.fetch_historical_data(
                    symbol=symbol, frequency="1d",
                    start_date=start, end_date=end,
                )
            logging.info(
                f"[{self.producer_name}] {symbol}({market}) 无 fetch fallback"
            )
            return None
        except Exception as e:
            logging.error(
                f"[{self.producer_name}] {symbol}({market}) fetch fallback 异常: {e}"
            )
            return None

    def _build_row(
        self, item: dict,
        current: Optional[PriceData],
        previous: Optional[PriceData],
    ) -> dict:
        if current is None or previous is None or not previous.close:
            return {**item, "missing": True}
        change_pct = (current.close - previous.close) / previous.close * 100
        return {
            **item,
            "missing": False,
            "current_price": current.close,
            "previous_price": previous.close,
            "change_pct": change_pct,
            "as_of": current.timestamp,
        }

    def _format_markdown(self, rows: List[dict]) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"📊 每日行情早报 {today}"]

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

        for label, group_rows in grouped.items():
            if not group_rows:
                continue
            lines.append("")
            lines.append(f"【{label}】")
            for r in group_rows:
                lines.append(self._format_row(r))
        return "\n".join(lines)

    @staticmethod
    def _format_row(r: dict) -> str:
        name = r["name"]
        symbol = r["symbol"]
        if r["missing"]:
            return f"{name}({symbol}) 暂无数据"
        arrow = "📈" if r["change_pct"] >= 0 else "📉"
        return (
            f"{arrow} {name}({symbol}) "
            f"{r['current_price']:.4f} "
            f"{r['change_pct']:+.2f}%"
        )
