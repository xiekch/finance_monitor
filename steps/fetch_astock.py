import logging
from datetime import datetime
from typing import Any, List

from steps.base import Step
from models.messages import PriceDataMessage, MessageType
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

    async def process(self, data: Any = None) -> List[PriceDataMessage]:
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

    async def _fetch_realtime(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        try:
            stock_data = await self.stock_fetcher.fetch_realtime_data(symbols)
            for data in stock_data:
                if not data or data.market not in _A_STOCK_MARKETS:
                    continue
                messages.append(PriceDataMessage(
                    payload=data.to_dict(), source=self.name, timestamp=datetime.now(),
                ))
        except Exception as e:
            logging.error(f"[{self.name}] 拉取实时数据失败: {e}")
        return messages

    async def _fetch_historical(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        fetcher_freq = {'daily': '1d', 'weekly': '1w'}[self.frequency]
        limit = 1 if self.frequency == 'weekly' else 7
        today = datetime.now().date()

        for sym in symbols:
            symbol = sym['symbol']
            try:
                rows = await self.stock_fetcher.fetch_historical_data(
                    symbol=symbol, frequency=fetcher_freq, limit=limit,
                    market=sym.get('market', ''),
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
