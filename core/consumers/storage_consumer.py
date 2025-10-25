from typing import Dict, Any
from datetime import datetime
import logging
from .base_consumer import BaseConsumer
from core.message_types import BaseMessage, PriceDataMessage, MessageType
from models.market_data import PriceData, MarketDataDB

class StorageConsumer(BaseConsumer):
    """数据存储消费者"""
    
    def __init__(self):
        super().__init__("StorageConsumer", [MessageType.PRICE_DATA, MessageType.HISTORICAL_PRICE_DATA])
        self.db = MarketDataDB()
    
    def process_message(self, message: Dict):
        """处理价格数据消息，保存到数据库"""
        price_message = PriceDataMessage.from_dict(message)
        
        # 转换为PriceData对象
        price_data = PriceData(**price_message.payload)
        
        # 保存到数据库
        self.db.save_price_data(price_data)
        logging.info(f"[{self.consumer_name}] 数据已保存: {price_data.symbol} {price_data.timestamp}")