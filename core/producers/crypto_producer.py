import asyncio
from apscheduler.triggers.cron import CronTrigger
from typing import Sequence
from datetime import datetime, timedelta
import logging
from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType, MessageType
from core.fetchers.crypto_fetcher import CryptoFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG

class CryptoProducer(BaseProducer):
    """加密货币数据生产者"""
    
    def __init__(self, run_immediately: bool = False, ignore_schedule: bool = False):
        super().__init__("CryptoProducer", run_immediately, ignore_schedule)
        self.crypto_fetcher = CryptoFetcher(API_CONFIG)
    
    def create_trigger(self) -> CronTrigger:
        """
        创建日级调度触发器
        每天美股收盘后运行（北京时间凌晨5点）
        """
        return CronTrigger(
            hour=5,           # 北京时间凌晨5点
            minute=0,
            second=0,
            day_of_week='mon-fri'  # 只在工作日运行
        )

    async def produce_data(self) -> Sequence[PriceDataMessage]:
        """生产加密货币数据"""
        messages = []
        # 设置日期范围 - 获取最近7天的数据确保包含交易日
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        try:
            crypto_symbols = MONITOR_CONFIG['daily']['crypto']
            if crypto_symbols:
                for symbol_info in crypto_symbols:
                    symbol = symbol_info['symbol']

                    # 直接使用 await 调用异步函数
                    # crypto_data = await self.crypto_fetcher.fetch_realtime_data(crypto_symbols)
                    historical_data = await self.crypto_fetcher.fetch_historical_data(
                        symbol=symbol,
                        frequency='1d',
                        start_date=start_date,
                        end_date=end_date
                    )   
                    for i, data in enumerate(historical_data):
                        data_date = data.timestamp.date()
                        today = datetime.now().date()
                        
                        # 判断消息类型：最后一条为实时数据，其他为历史数据
                        if i == len(historical_data) - 1:
                            # 最后一条数据作为实时价格数据
                            message_type = MessageType.PRICE_DATA
                            log_prefix = "生产日线数据"
                            
                            # 如果数据日期不是今天，说明是历史数据
                            if data_date != today:
                                logging.info(f"[{self.producer_name}] {symbol} 获取到历史数据作为最新数据，日期: {data_date}")
                        else:
                            # 其他数据作为历史价格数据
                            message_type = MessageType.HISTORICAL_PRICE_DATA
                            log_prefix = "生产历史日线数据"

                        message = PriceDataMessage(
                            payload=data.to_dict(),
                            timestamp=data.timestamp,
                            message_type=message_type,
                            source=self.producer_name
                        )
                        messages.append(message)

                        logging.info(f"[{self.producer_name}] {log_prefix}: {data.symbol} "
                            f"收盘价: ${data.close:.2f}, 日期: {data_date}")

        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产加密货币数据失败: {e}")
            raise e
        
        return messages
    
    def start_websocket_production(self, callback=None):
        """启动WebSocket实时数据生产"""
        crypto_symbols = MONITOR_CONFIG['minute']['crypto']
        
        def ws_callback(price_data):
            """WebSocket数据回调"""
            message = PriceDataMessage(
                payload=price_data.to_dict(),
                source=f"{self.producer_name}_WebSocket"
            )
            self.publish_message(message)
            
            if callback:
                callback(price_data)
        
        self.crypto_fetcher.start_websocket_monitoring(crypto_symbols, ws_callback)