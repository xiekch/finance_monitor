import logging
from datetime import datetime, timedelta
from typing import List

from steps.base import Step
from models.market import PriceData
from fetchers.crypto_fetcher import CryptoFetcher
from config.settings import API_CONFIG
from config.monitor import MONITOR_CONFIG


class FetchCrypto(Step):

    def __init__(self, frequency: str):
        if frequency not in ('minute', 'daily', 'weekly'):
            raise ValueError(f"未知 frequency: {frequency}")
        self.frequency = frequency
        self.name = f"FetchCrypto({frequency})"
        self.fetcher = CryptoFetcher(API_CONFIG)

    async def process(self, items: list = ()) -> List[PriceData]:
        symbols = [s for s in MONITOR_CONFIG.get('crypto', []) if s['frequency'] == self.frequency]
        if not symbols:
            logging.warning(f"[{self.name}] 未找到加密货币标的配置")
            return []

        logging.info(f"[{self.name}] 开始处理 {len(symbols)} 个加密货币标的")

        if self.frequency == 'minute':
            return await self._fetch_realtime(symbols)
        return await self._fetch_historical(symbols)

    async def _fetch_realtime(self, symbols: List[dict]) -> List[PriceData]:
        results: List[PriceData] = []
        try:
            data_list = await self.fetcher.fetch_realtime_data(symbols)
            results = [d for d in data_list if d]
        except Exception as e:
            logging.error(f"[{self.name}] 拉取实时数据失败: {e}")
        return results

    async def _fetch_historical(self, symbols: List[dict]) -> List[PriceData]:
        results: List[PriceData] = []
        fetcher_freq = {'daily': '1d', 'weekly': '1w'}[self.frequency]
        end = datetime.now()
        window_days = 14 if self.frequency == 'weekly' else 7
        start = end - timedelta(days=window_days)

        for sym in symbols:
            symbol = sym['symbol']
            try:
                rows = await self.fetcher.fetch_historical_data(
                    symbol=symbol, frequency=fetcher_freq,
                    start_date=start, end_date=end,
                )
                results.extend(rows or [])
            except Exception as e:
                logging.error(f"[{self.name}] {symbol} 失败: {e}")
        return results
