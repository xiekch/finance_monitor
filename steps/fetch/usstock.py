import logging
from datetime import datetime, timedelta
from typing import List

from steps.base import Step
from models.market import PriceData
from fetchers.us_stock_yf_fetcher import USStockYfFetcher
from config.settings import API_CONFIG
from config.monitor import MONITOR_CONFIG


class FetchUSStock(Step):

    def __init__(self, frequency: str):
        if frequency not in ('minute', 'daily', 'weekly'):
            raise ValueError(f"未知 frequency: {frequency}")
        self.frequency = frequency
        self.name = f"FetchUSStock({frequency})"
        self.fetcher = USStockYfFetcher(API_CONFIG)

    async def process(self, items: list = ()) -> List[PriceData]:
        symbols = self._get_symbols()
        if not symbols:
            logging.warning(f"[{self.name}] 未找到美股/港股标的配置")
            return []

        logging.info(f"[{self.name}] 开始处理 {len(symbols)} 个美股标的")

        if self.frequency == 'minute':
            return await self._fetch_realtime(symbols)
        return await self._fetch_historical(symbols)

    async def _fetch_realtime(self, symbols: List[dict]) -> List[PriceData]:
        results: List[PriceData] = []
        try:
            stock_data = await self.fetcher.fetch_realtime_data(symbols)
            results = [d for d in stock_data if d]
        except Exception as e:
            logging.error(f"[{self.name}] 拉取实时数据失败: {e}")
        return results

    async def _fetch_historical(self, symbols: List[dict]) -> List[PriceData]:
        results: List[PriceData] = []
        fetcher_freq = {'daily': '1d', 'weekly': '1w'}[self.frequency]
        window_days = 7 if self.frequency == 'daily' else 14

        for sym in symbols:
            symbol = sym['symbol']
            try:
                end = datetime.now()
                rows = await self.fetcher.fetch_historical_data(
                    symbol=symbol, frequency=fetcher_freq,
                    start_date=end - timedelta(days=window_days), end_date=end,
                    market=sym.get('market', 'US'),
                )
                results.extend(rows or [])
            except Exception as e:
                logging.error(f"[{self.name}] {symbol} 失败: {e}")
        return results

    def _get_symbols(self) -> List[dict]:
        yf_markets = ('US', 'NASDAQ', 'NYSE', 'HK', 'JP', 'KR')
        result = []
        for s in MONITOR_CONFIG.get('stocks', []):
            if s['frequency'] != self.frequency:
                continue
            market = s.get('market', '')
            symbol = s.get('symbol', '')
            if market in yf_markets:
                result.append({
                    'symbol': symbol,
                    'market': market,
                    'name': s.get('name', symbol),
                    'threshold': s.get('threshold', 2.0),
                })
            elif len(symbol) <= 5 and symbol.isalpha() and symbol.isupper():
                result.append({
                    'symbol': symbol, 'market': 'US',
                    'name': s.get('name', symbol),
                    'threshold': s.get('threshold', 2.0),
                })
        return result
