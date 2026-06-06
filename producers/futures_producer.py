from typing import Sequence, List, Optional
from datetime import datetime
import logging

from apscheduler.triggers.base import BaseTrigger
from .base_producer import BaseProducer
from models.messages import PriceDataMessage, MessageType
from fetchers.futures_fetcher import FuturesFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG


class FuturesProducer(BaseProducer):
    """期货数据生产者，按 frequency 区分获取方式

    - frequency='minute'：调用 fetch_realtime_data 拉取实时数据
    - frequency='daily' / 'weekly'：调用 fetch_historical_data 拉取历史数据
    """

    _NAME_BY_FREQ = {
        'minute': 'FuturesMinuteProducer',
        'daily':  'FuturesDailyProducer',
        'weekly': 'FuturesWeeklyProducer',
    }

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
        self.futures_fetcher = FuturesFetcher(API_CONFIG)

    async def produce_data(self) -> Sequence[PriceDataMessage]:
        symbols = [s for s in MONITOR_CONFIG.get('futures', []) if s['frequency'] == self.frequency]
        if not symbols:
            logging.warning(f"[{self.producer_name}] 未找到期货标的配置")
            return []

        logging.info(f"[{self.producer_name}] 开始处理 {len(symbols)} 个期货标的")

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
            futures_data = await self.futures_fetcher.fetch_realtime_data(symbols)
            for data in futures_data:
                if not data:
                    continue
                messages.append(PriceDataMessage(
                    payload=data.to_dict(),
                    source=self.producer_name,
                    timestamp=datetime.now(),
                ))
                logging.info(
                    f"[{self.producer_name}] 生产实时数据: {data.symbol} ¥{data.close:.2f}"
                )
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产期货实时数据失败: {e}")
        return messages

    async def _produce_historical(self, symbols: List[dict]) -> List[PriceDataMessage]:
        messages: List[PriceDataMessage] = []
        fetcher_freq = self._HISTORICAL_FETCH_FREQ[self.frequency]
        today = datetime.now().date()
        limit = 1 if self.frequency == 'weekly' else 7

        for symbol_info in symbols:
            symbol = symbol_info['symbol']
            market = symbol_info.get('market', 'FUT')
            try:
                historical_data = await self.futures_fetcher.fetch_historical_data(
                    symbol=symbol, frequency=fetcher_freq, limit=limit, market=market,
                )
                if not historical_data:
                    logging.warning(
                        f"[{self.producer_name}] 未获取到 {symbol} 的{self.frequency}数据"
                    )
                    continue

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
                        f"收盘价: ¥{data.close:.2f}, 日期: {data.timestamp.date()}"
                    )
            except Exception as e:
                logging.error(
                    f"[{self.producer_name}] 处理标的 {symbol} 失败: {e}"
                )
                continue
        return messages
