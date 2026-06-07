import logging
from datetime import datetime, timedelta
from typing import Any, List

from steps.base import Step
from models.messages import PriceDataMessage, MessageType
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

    async def process(self, data: Any = None) -> List[PriceDataMessage]:
        symbols = self._get_symbols()
        if not symbols:
            logging.warning(f"[{self.name}] 未找到美股标的配置")
            return []

        logging.info(f"[{self.name}] 开始处理 {len(symbols)} 个美股标的")

        if self.frequency == 'minute':
            return await self._fetch_realtime(symbols)
        return await self._fetch_historical(symbols)

    async def _fetch_realtime(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        try:
            stock_data = await self.fetcher.fetch_realtime_data(symbols)
            for d in stock_data:
                if not d:
                    continue
                messages.append(PriceDataMessage(
                    payload=d.to_dict(), source=self.name, timestamp=datetime.now(),
                ))
        except Exception as e:
            logging.error(f"[{self.name}] 拉取实时数据失败: {e}")
        return messages

    async def _fetch_historical(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        fetcher_freq = {'daily': '1d', 'weekly': '1w'}[self.frequency]
        today = datetime.now().date()

        for sym in symbols:
            symbol = sym['symbol']
            try:
                if self.frequency == 'daily':
                    end = datetime.now()
                    rows = await self.fetcher.fetch_historical_data(
                        symbol=symbol, frequency=fetcher_freq,
                        start_date=end - timedelta(days=7), end_date=end,
                    )
                else:
                    end = datetime.now()
                    rows = await self.fetcher.fetch_historical_data(
                        symbol=symbol, frequency=fetcher_freq,
                        start_date=end - timedelta(days=14), end_date=end,
                    )
                if not rows:
                    continue
                for i, d in enumerate(rows):
                    mt = MessageType.PRICE_DATA if i == len(rows) - 1 else MessageType.HISTORICAL_PRICE_DATA
                    messages.append(PriceDataMessage(
                        payload=d.to_dict(), source=self.name,
                        timestamp=d.timestamp, message_type=mt,
                    ))
            except Exception as e:
                logging.error(f"[{self.name}] {symbol} 失败: {e}")
        return messages

    def _get_symbols(self) -> List[dict]:
        us_markets = ('US', 'NASDAQ', 'NYSE')
        result = []
        for s in MONITOR_CONFIG.get('stocks', []):
            if s['frequency'] != self.frequency:
                continue
            market = s.get('market', '')
            symbol = s.get('symbol', '')
            if market in us_markets or (len(symbol) <= 5 and symbol.isalpha() and symbol.isupper()):
                result.append({
                    'symbol': symbol, 'market': 'US',
                    'name': s.get('name', symbol),
                    'threshold': s.get('threshold', 2.0),
                })
        return result
