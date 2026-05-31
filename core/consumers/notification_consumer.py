from typing import Dict

from .base_consumer import BaseConsumer
from core.message_types import (
    BaseMessage,
    VolatilityAlertMessage,
    SystemEventMessage,
    AIBriefingMessage,
    MessageType,
)
from core.notifiers.wechat_notifier import WeChatNotifier
from config.social import SOCIAL_CONFIG
import logging


class NotificationConsumer(BaseConsumer):
    """通知发送消费者"""

    def __init__(self):
        super().__init__("NotificationConsumer", [
            MessageType.VOLATILITY_ALERT,
            MessageType.AI_BRIEFING,
            # MessageType.SYSTEM_EVENT
        ])
        self.wechat_notifier = WeChatNotifier()

    def process_message(self, message: Dict):
        message_type = MessageType(message["message_type"])
        if message_type == MessageType.VOLATILITY_ALERT:
            self._handle_volatility_alert(VolatilityAlertMessage.from_dict(message))
        elif message_type == MessageType.SYSTEM_EVENT:
            self._handle_system_event(SystemEventMessage.from_dict(message))
        elif message_type == MessageType.AI_BRIEFING:
            self._handle_briefing(AIBriefingMessage.from_dict(message))

    def _handle_volatility_alert(self, message: BaseMessage):
        alert_data = message.payload
        from models.market_data import VolatilityAlert
        from datetime import datetime

        alert = VolatilityAlert(
            symbol=alert_data["symbol"],
            name=alert_data["name"],
            frequency=alert_data["frequency"],
            current_change=alert_data["current_change"],
            threshold=alert_data["threshold"],
            current_price=alert_data["current_price"],
            previous_price=alert_data["previous_price"],
            timestamp=datetime.fromisoformat(alert_data["timestamp"]),
        )
        if self.wechat_notifier.send_alert(alert):
            logging.info(f"[{self.consumer_name}] 告警通知发送成功: {alert.name}")
        else:
            logging.error(f"[{self.consumer_name}] 告警通知发送失败: {alert.name}")

    def _handle_system_event(self, message: BaseMessage):
        event_type = message.payload["event_type"]
        event_data = message.payload["event_data"]
        if event_type == "system_start":
            self.wechat_notifier.send_test_message()
            logging.info(f"[{self.consumer_name}] 系统启动通知已发送")
        elif event_type == "system_shutdown":
            shutdown_message = f"🛑 市场监控系统已关闭\n时间: {event_data.get('timestamp', 'N/A')}"
            self.wechat_notifier._send_wecom_message(shutdown_message)
            logging.info(f"[{self.consumer_name}] 系统关闭通知已发送")

    def _handle_briefing(self, message: BaseMessage):
        markdown = message.payload.get("markdown", "")
        ok = self.wechat_notifier.send_markdown(
            markdown, max_chars=SOCIAL_CONFIG["push_max_chars"]
        )
        degraded = message.payload.get("degraded")
        if ok:
            logging.info(f"[{self.consumer_name}] AI 简报推送成功 degraded={degraded}")
        else:
            logging.error(f"[{self.consumer_name}] AI 简报推送失败 degraded={degraded}")
