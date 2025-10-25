from typing import Dict, Any
from datetime import datetime

from .base_consumer import BaseConsumer
from core.message_types import BaseMessage, PriceDataMessage, VolatilityAlertMessage, MessageType, FrequencyType
from core.analyzers.volatility_analyzer import VolatilityAnalyzer
from core.threshold_manager import ThresholdManager
from models.market_data import PriceData

class VolatilityConsumer(BaseConsumer):
    """波动分析消费者"""
    
    def __init__(self):
        super().__init__("VolatilityConsumer", [MessageType.PRICE_DATA])
        self.threshold_manager = ThresholdManager()
        self.volatility_analyzer = VolatilityAnalyzer(self.threshold_manager)
    
    def process_message(self, message: BaseMessage):
        """处理价格数据消息，分析波动"""
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
            
            # 分析波动
            if price_message.frequency == FrequencyType.MINUTE:
                alert = self.volatility_analyzer.analyze_minute_volatility(price_data)
            elif price_message.frequency == FrequencyType.DAILY:
                alert = self.volatility_analyzer.analyze_daily_volatility(price_data)
            elif price_message.frequency == FrequencyType.WEEKLY:
                alert = self.volatility_analyzer.analyze_weekly_volatility(price_data)
            else:
                alert = None
            
            # 如果有告警，发布告警消息
            if alert:
                alert_message = VolatilityAlertMessage(
                    alert_data={
                        'symbol': alert.symbol,
                        'name': alert.name,
                        'frequency': alert.frequency,
                        'current_change': alert.current_change,
                        'threshold': alert.threshold,
                        'current_price': alert.current_price,
                        'previous_price': alert.previous_price,
                        'timestamp': alert.timestamp.isoformat()
                    },
                    source=self.consumer_name
                )
                
                # 发布告警消息
                from core.message_queue import mq
                mq.publish(MessageType.VOLATILITY_ALERT.value, alert_message.to_dict())
                print(f"[{self.consumer_name}] 发现波动告警: {alert.name} {alert.current_change:.2f}%")