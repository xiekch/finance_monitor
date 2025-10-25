from typing import Dict, Any

from .base_consumer import BaseConsumer
from core.message_types import BaseMessage, VolatilityAlertMessage, SystemEventMessage, MessageType
from core.notifiers.wechat_notifier import WeChatNotifier
import logging

class NotificationConsumer(BaseConsumer):
    """通知发送消费者"""
    
    def __init__(self):
        super().__init__("NotificationConsumer", [
            MessageType.VOLATILITY_ALERT, 
            MessageType.SYSTEM_EVENT
        ])
        self.wechat_notifier = WeChatNotifier()
    
    def process_message(self, message: Dict):
        """处理告警和系统事件消息，发送通知"""
        message_type = MessageType(message['message_type'])
        if message_type == MessageType.VOLATILITY_ALERT:
            message = VolatilityAlertMessage.from_dict(message)
            self._handle_volatility_alert(message)
        elif message_type == MessageType.SYSTEM_EVENT:
            message = SystemEventMessage.from_dict(message)
            self._handle_system_event(message)
    
    def _handle_volatility_alert(self, message: BaseMessage):
        """处理波动告警"""
        alert_data = message.payload
        
        # 创建告警对象（简化版）
        from models.market_data import VolatilityAlert
        from datetime import datetime
        
        alert = VolatilityAlert(
            symbol=alert_data['symbol'],
            name=alert_data['name'],
            frequency=alert_data['frequency'],
            current_change=alert_data['current_change'],
            threshold=alert_data['threshold'],
            current_price=alert_data['current_price'],
            previous_price=alert_data['previous_price'],
            timestamp=datetime.fromisoformat(alert_data['timestamp'])
        )
        
        # 发送通知
        success = self.wechat_notifier.send_alert(alert)
        if success:
            logging.info(f"[{self.consumer_name}] 告警通知发送成功: {alert.name}")
        else:
            logging.error(f"[{self.consumer_name}] 告警通知发送失败: {alert.name}")
    
    def _handle_system_event(self, message: BaseMessage):
        """处理系统事件"""
        event_type = message.payload['event_type']
        event_data = message.payload['event_data']

        if event_type == 'system_start':
            self.wechat_notifier.send_test_message()
            logging.info(f"[{self.consumer_name}] 系统启动通知已发送")
        elif event_type == 'system_shutdown':
            # 发送系统关闭通知
            shutdown_message = f"🛑 市场监控系统已关闭\n时间: {event_data.get('timestamp', 'N/A')}"
            self.wechat_notifier._send_wecom_message(shutdown_message)
            logging.info(f"[{self.consumer_name}] 系统关闭通知已发送")