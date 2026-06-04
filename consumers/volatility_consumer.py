import logging
from .base_consumer import BaseConsumer
from infra.message_queue import mq
from models.messages import BaseMessage, VolatilityAlertMessage, MessageType, FrequencyType
from analyzers.volatility_analyzer import VolatilityAnalyzer
from analyzers.threshold_manager import ThresholdManager
from models.market import PriceData

class VolatilityConsumer(BaseConsumer):
    """波动分析消费者"""

    def __init__(self):
        super().__init__("VolatilityConsumer", [MessageType.PRICE_DATA])
        self.threshold_manager = ThresholdManager()
        self.volatility_analyzer = VolatilityAnalyzer(self.threshold_manager)

    def process_message(self, message: BaseMessage):
        """处理价格数据消息，分析波动"""
        price_data = PriceData.from_dict(message.payload)

        frequency = FrequencyType(price_data.frequency)
        if frequency == FrequencyType.MINUTE:
            alert = self.volatility_analyzer.analyze_minute_volatility(price_data)
        elif frequency == FrequencyType.DAILY:
            alert = self.volatility_analyzer.analyze_daily_volatility(price_data)
        elif frequency == FrequencyType.WEEKLY:
            alert = self.volatility_analyzer.analyze_weekly_volatility(price_data)
        else:
            alert = None
        logging.info(f"[{self.consumer_name}] 发现告警: {alert}")

        if alert:
            alert_message = VolatilityAlertMessage(
                payload={
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
            mq.publish(MessageType.VOLATILITY_ALERT.value, alert_message)
            logging.info(f"[{self.consumer_name}] 发现波动告警: {alert.name} {alert.current_change:.2f}%")