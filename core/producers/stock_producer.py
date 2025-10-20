import asyncio
from typing import List
from datetime import datetime

from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType, MessageType
from core.fetchers.stock_fetcher import StockFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG

class StockProducer(BaseProducer):
    """股票数据生产者"""
    
    def __init__(self):
        super().__init__("StockProducer")
        self.stock_fetcher = StockFetcher(API_CONFIG)
        self.frequency_mapping = {
            'minute': FrequencyType.MINUTE,
            'daily': FrequencyType.DAILY,
            'weekly': FrequencyType.WEEKLY
        }
    
    def produce_data(self) -> List[PriceDataMessage]:
        """生产股票数据"""
        messages = []
        
        # 由于produce_data是同步方法，我们需要运行异步函数
        try:
            # 获取分钟级数据
            stock_symbols = self._get_symbols_by_frequency('minute', 'stocks')
            if stock_symbols:
                # 在事件循环中运行异步函数
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                stock_data = loop.run_until_complete(
                    self.stock_fetcher.fetch_realtime_data(stock_symbols)
                )
                loop.close()
                
                for data in stock_data:
                    message = PriceDataMessage(
                        symbol=data.symbol,
                        market=data.market,
                        frequency=FrequencyType.MINUTE,
                        price_data=data.to_dict(),
                        source=self.producer_name
                    )
                    messages.append(message)
        
        except Exception as e:
            print(f"[{self.producer_name}] 生产股票数据失败: {e}")
        
        return messages
    
    def _get_symbols_by_frequency(self, frequency: str, asset_type: str):
        """获取指定频率和资产类型的标的"""
        return MONITOR_CONFIG.get(frequency, {}).get(asset_type, [])
    
    def produce_historical_data(self, frequency: FrequencyType):
        """生产历史数据（用于日频和周频分析）"""
        # 实现日频和周频数据生产
        pass