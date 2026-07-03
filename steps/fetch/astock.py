import logging
from typing import List

from steps.base import Step
from models.market import PriceData
from fetchers.astock_fetcher import AStockFetcher
from config.settings import API_CONFIG
from config.monitor import MONITOR_CONFIG


_A_STOCK_MARKETS = ('SH', 'SZ')


class FetchAStock(Step):

    def __init__(self, frequency: str):
        if frequency not in ('minute', 'daily', 'weekly'):
            raise ValueError(f"未知 frequency: {frequency}")
        self.frequency = frequency
        self.name = f"FetchAStock({frequency})"
        self.stock_fetcher = AStockFetcher(API_CONFIG)

    async def process(self, items: list = ()) -> List[PriceData]:
        symbols = [
            s for s in MONITOR_CONFIG.get('stocks', [])
            if s['frequency'] == self.frequency and s.get('market') in _A_STOCK_MARKETS
        ]
        if not symbols:
            logging.warning(f"[{self.name}] 未找到 A 股标的配置")
            return []

        logging.info(f"[{self.name}] 开始处理 {len(symbols)} 个 A 股标的")

        if self.frequency == 'minute':
            return await self._fetch_realtime(symbols)
        return await self._fetch_historical(symbols)

    async def _fetch_realtime(self, symbols: List[dict]) -> List[PriceData]:
        results: List[PriceData] = []
        try:
            stock_data = await self.stock_fetcher.fetch_realtime_data(symbols)
            results = [
                d for d in stock_data if d and d.market in _A_STOCK_MARKETS
            ]
        except Exception as e:
            logging.error(f"[{self.name}] 拉取实时数据失败: {e}")
        return results

    async def _fetch_historical(self, symbols: List[dict]) -> List[PriceData]:
        results: List[PriceData] = []
        fetcher_freq = {'daily': '1d', 'weekly': '1w'}[self.frequency]
        limit = 1 if self.frequency == 'weekly' else 7

        for sym in symbols:
            symbol = sym['symbol']
            try:
                rows = await self.stock_fetcher.fetch_historical_data(
                    symbol=symbol, frequency=fetcher_freq, limit=limit,
                    market=sym.get('market', ''),
                )
                results.extend(rows or [])
            except Exception as e:
                logging.error(f"[{self.name}] {symbol} 失败: {e}")
        return results
