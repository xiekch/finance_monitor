import asyncio
from typing import List
from datetime import datetime

from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType
from core.fetchers.crypto_fetcher import CryptoFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG

class CryptoProducer(BaseProducer):
    """加密货币数据生产者"""
    
    def __init__(self):
        super().__init__("CryptoProducer")
        self.crypto_fetcher = CryptoFetcher(API_CONFIG)
    
    def produce_data(self) -> List[PriceDataMessage]:
        """生产加密货币数据"""
        messages = []
        
        try:
            # 获取分钟级数据
            crypto_symbols = MONITOR_CONFIG['minute']['crypto']
            if crypto_symbols:
                # 在事件循环中运行异步函数
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                crypto_data = loop.run_until_complete(
                    self.crypto_fetcher.fetch_realtime_data(crypto_symbols)
                )
                loop.close()
                
                for data in crypto_data:
                    message = PriceDataMessage(
                        symbol=data.symbol,
                        market=data.market,
                        frequency=FrequencyType.MINUTE,
                        price_data=data.to_dict(),
                        source=self.producer_name
                    )
                    messages.append(message)
        
        except Exception as e:
            print(f"[{self.producer_name}] 生产加密货币数据失败: {e}")
        
        return messages
    
    def start_websocket_production(self, callback=None):
        """启动WebSocket实时数据生产"""
        crypto_symbols = MONITOR_CONFIG['minute']['crypto']
        
        def ws_callback(price_data):
            """WebSocket数据回调"""
            message = PriceDataMessage(
                symbol=price_data.symbol,
                market=price_data.market,
                frequency=FrequencyType.MINUTE,
                price_data=price_data.to_dict(),
                source=f"{self.producer_name}_WebSocket"
            )
            self.publish_message(message)
            
            if callback:
                callback(price_data)
        
        self.crypto_fetcher.start_websocket_monitoring(crypto_symbols, ws_callback)