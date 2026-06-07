import logging
from datetime import datetime, timedelta
from typing import Any, List

from steps.base import Step
from models.messages import PriceDataMessage, MessageType
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

    async def process(self, data: Any = None) -> List[PriceDataMessage]:
        symbols = [s for s in MONITOR_CONFIG.get('crypto', []) if s['frequency'] == self.frequency]
        if not symbols:
            logging.warning(f"[{self.name}] 未找到加密货币标的配置")
            return []

        logging.info(f"[{self.name}] 开始处理 {len(symbols)} 个加密货币标的")

        if self.frequency == 'minute':
            return await self._fetch_realtime(symbols)
        return await self._fetch_historical(symbols)

    async def _fetch_realtime(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        try:
            data_list = await self.fetcher.fetch_realtime_data(symbols)
            for d in data_list:
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
        end = datetime.now()
        window_days = 14 if self.frequency == 'weekly' else 7
        start = end - timedelta(days=window_days)
        today = end.date()

        for sym in symbols:
            symbol = sym['symbol']
            try:
                rows = await self.fetcher.fetch_historical_data(
                    symbol=symbol, frequency=fetcher_freq,
                    start_date=start, end_date=end,
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
