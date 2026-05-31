from typing import List, Optional
from datetime import datetime, timedelta
import logging

from apscheduler.triggers.base import BaseTrigger

from .base_producer import BaseProducer
from models.messages import PriceDataMessage, MessageType
from fetchers.us_stock_yf_fetcher import USStockYfFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG


class USStockProducer(BaseProducer):
    """美股数据生产者，按 frequency 区分获取方式

    - frequency='minute'：调用 fetch_realtime_data 拉取实时分钟数据
    - frequency='daily' / 'weekly'：调用 fetch_historical_data 拉取历史数据
    """

    _NAME_BY_FREQ = {
        'minute': 'USStockMinuteProducer',
        'daily':  'USStockDailyProducer',
        'weekly': 'USStockWeeklyProducer',
    }

    # 历史数据每个频率对应的 (fetcher_frequency, fetch_kwargs_builder)
    _HISTORICAL_FETCH_FREQ = {
        'daily':  '1d',
        'weekly': '1w',
    }

    def __init__(
        self,
        frequency: str,
        trigger: Optional[BaseTrigger] = None,
        run_immediately: bool = False,
        ignore_schedule: bool = False,
    ):
        if frequency not in self._NAME_BY_FREQ:
            raise ValueError(
                f"未知 frequency: {frequency}; 可选: {sorted(self._NAME_BY_FREQ)}"
            )
        super().__init__(
            self._NAME_BY_FREQ[frequency], trigger, run_immediately, ignore_schedule
        )
        self.frequency = frequency
        self.us_stock_fetcher = USStockYfFetcher(API_CONFIG)

    async def produce_data(self) -> List[PriceDataMessage]:
        symbols = self._get_us_stock_symbols(self.frequency)
        if not symbols:
            logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
            return []

        logging.info(f"[{self.producer_name}] 开始处理 {len(symbols)} 个美股标的")

        if self.frequency == 'minute':
            messages = await self._produce_realtime(symbols)
        else:
            messages = await self._produce_historical(symbols)

        price_count = sum(1 for m in messages if m.message_type == MessageType.PRICE_DATA)
        hist_count = sum(1 for m in messages if m.message_type == MessageType.HISTORICAL_PRICE_DATA)
        logging.info(
            f"[{self.producer_name}] 生产完成，共生成 {len(messages)} 条数据 "
            f"(实时: {price_count}, 历史: {hist_count})"
        )
        return messages

    async def _produce_realtime(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        try:
            stock_data = await self.us_stock_fetcher.fetch_realtime_data(symbols)
            for data in stock_data:
                if not data:
                    continue
                message = PriceDataMessage(
                    payload=data.to_dict(),
                    source=self.producer_name,
                    timestamp=datetime.now(),
                )
                messages.append(message)
                logging.info(
                    f"[{self.producer_name}] 生产分钟数据: {data.symbol} ${data.close:.2f}"
                )
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产美股分钟数据失败: {e}")
        return messages

    async def _produce_historical(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        fetcher_freq = self._HISTORICAL_FETCH_FREQ[self.frequency]

        for symbol_info in symbols:
            symbol = symbol_info['symbol']
            try:
                historical_data = await self._fetch_historical_window(symbol, fetcher_freq)
                if not historical_data:
                    logging.warning(
                        f"[{self.producer_name}] 未获取到 {symbol} 的{self.frequency}数据"
                    )
                    continue

                today = datetime.now().date()
                for i, data in enumerate(historical_data):
                    is_last = i == len(historical_data) - 1
                    if is_last:
                        message_type = MessageType.PRICE_DATA
                        log_prefix = f"生产{self.frequency}数据"
                        if data.timestamp.date() != today:
                            logging.info(
                                f"[{self.producer_name}] {symbol} 获取到历史数据作为最新数据，"
                                f"日期: {data.timestamp.date()}"
                            )
                    else:
                        message_type = MessageType.HISTORICAL_PRICE_DATA
                        log_prefix = f"生产历史{self.frequency}数据"

                    messages.append(PriceDataMessage(
                        payload=data.to_dict(),
                        source=self.producer_name,
                        timestamp=data.timestamp,
                        message_type=message_type,
                    ))
                    logging.info(
                        f"[{self.producer_name}] {log_prefix}: {data.symbol} "
                        f"收盘价: ${data.close:.2f}, 日期: {data.timestamp.date()}"
                    )

                logging.info(
                    f"[{self.producer_name}] {symbol} 共处理 {len(historical_data)} 条数据"
                )
            except Exception as e:
                logging.error(
                    f"[{self.producer_name}] 处理标的 {symbol_info.get('symbol')} 失败: {e}"
                )
                continue
        return messages

    async def _fetch_historical_window(self, symbol: str, fetcher_freq: str):
        """按频率拉取历史数据；daily 用 7 天窗口，weekly 取最近 1 条。"""
        if self.frequency == 'daily':
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            return await self.us_stock_fetcher.fetch_historical_data(
                symbol=symbol,
                frequency=fetcher_freq,
                start_date=start_date,
                end_date=end_date,
            )
        # weekly
        return await self.us_stock_fetcher.fetch_historical_data(
            symbol=symbol,
            frequency=fetcher_freq,
            limit=1,
        )

    def _get_us_stock_symbols(self, frequency: str) -> List[dict]:
        all_symbols = MONITOR_CONFIG.get(frequency, {}).get('stocks', [])
        us_stock_symbols = []
        for symbol_info in all_symbols:
            market = symbol_info.get('market', '')
            symbol = symbol_info.get('symbol', '')
            if market in ['US', 'NASDAQ', 'NYSE'] or self._is_us_stock_symbol(symbol):
                us_stock_symbols.append({
                    'symbol': symbol,
                    'market': 'US',
                    'name': symbol_info.get('name', symbol),
                    'threshold': symbol_info.get('threshold', 2.0),
                })
        return us_stock_symbols

    @staticmethod
    def _is_us_stock_symbol(symbol: str) -> bool:
        return len(symbol) <= 5 and symbol.isalpha() and symbol.isupper()
