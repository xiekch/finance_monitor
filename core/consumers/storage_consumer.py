from typing import Dict, Any
from datetime import datetime

from .base_consumer import BaseConsumer
from core.message_types import BaseMessage, PriceDataMessage, MessageType
from models.market_data import PriceData, MarketDataDB

class StorageConsumer(BaseConsumer):
    """数据存储消费者"""
    
    def __init__(self):
        super().__init__("StorageConsumer", [MessageType.PRICE_DATA])
        self.db = MarketDataDB()
    
    def process_message(self, message: BaseMessage):
        """处理价格数据消息，保存到数据库"""
        if message.message_type == MessageType.PRICE_DATA:
            price_message = PriceDataMessage.from_dict(message.to_dict())
            
            # 转换为PriceData对象
            price_data = PriceData(
                symbol=price_message.symbol,
                market=price_message.market,
                timestamp=datetime.fromisoformat(price_message.payload['timestamp']),
                open=price_message.payload['open'],
                high=price_message.payload['high'],
                low=price_message.payload['low'],
                close=price_message.payload['close'],
                volume=price_message.payload.get('volume', 0),
                frequency=price_message.payload.get('frequency', '1m')
            )
            
            # 保存到数据库
            self.db.save_price_data(price_data)
            print(f"[{self.consumer_name}] 数据已保存: {price_data.symbol} {price_data.timestamp}")