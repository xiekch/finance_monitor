from .base_consumer import BaseConsumer
from models.messages import BaseMessage, MessageType
from notifiers.wechat_notifier import WeChatNotifier
from config.social import SOCIAL_CONFIG
import logging
import threading
from datetime import date as _date


class NotificationConsumer(BaseConsumer):
    """通知发送消费者"""

    # 日/周频告警去重；minute 不去重（按设计每次穿越阈值都推）
    _DEDUP_FREQUENCIES = frozenset({"daily", "weekly"})

    def __init__(self):
        super().__init__("NotificationConsumer", [
            MessageType.VOLATILITY_ALERT,
            MessageType.AI_BRIEFING,
            MessageType.MARKET_BRIEFING,
            # MessageType.SYSTEM_EVENT
        ])
        self.wechat_notifier = WeChatNotifier()
        # key = (symbol, frequency, alert_date)
        # 进程重启会清空 —— 重启后宁可漏一次也比误重发一遍可控
        self._alerted_keys: set[tuple[str, str, _date]] = set()
        self._dedup_lock = threading.Lock()

    def process_message(self, message: BaseMessage):
        mt = message.message_type
        if mt == MessageType.VOLATILITY_ALERT:
            self._handle_volatility_alert(message)
        elif mt == MessageType.SYSTEM_EVENT:
            self._handle_system_event(message)
        elif mt == MessageType.AI_BRIEFING:
            self._handle_briefing(message)
        elif mt == MessageType.MARKET_BRIEFING:
            self._handle_market_briefing(message)

    def _handle_volatility_alert(self, message: BaseMessage):
        alert_data = message.payload
        from models.market import VolatilityAlert
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

        if alert.frequency in self._DEDUP_FREQUENCIES:
            key = (alert.symbol, alert.frequency, alert.timestamp.date())
            with self._dedup_lock:
                if key in self._alerted_keys:
                    logging.info(
                        f"[{self.consumer_name}] 告警当天已推送，跳过: "
                        f"{alert.name}({alert.symbol}) {alert.frequency}"
                    )
                    return
                self._alerted_keys.add(key)

        if self.wechat_notifier.send_alert(alert):
            logging.info(f"[{self.consumer_name}] 告警通知发送成功: {alert.name}")
        else:
            logging.error(f"[{self.consumer_name}] 告警通知发送失败: {alert.name}")

    def _handle_system_event(self, message: BaseMessage):
        event_type = message.payload["event_type"]
        event_data = message.payload["event_data"]
        if event_type == "system_start":
            self.wechat_notifier.send_text(
                "🔔 市场波动监控系统测试\n系统启动成功，监控服务正常运行中..."
            )
            logging.info(f"[{self.consumer_name}] 系统启动通知已发送")
        elif event_type == "system_shutdown":
            shutdown_message = f"🛑 市场监控系统已关闭\n时间: {event_data.get('timestamp', 'N/A')}"
            self.wechat_notifier.send_text(shutdown_message)
            logging.info(f"[{self.consumer_name}] 系统关闭通知已发送")

    def _handle_briefing(self, message: BaseMessage):
        markdown = message.payload.get("markdown", "")
        degraded = message.payload.get("degraded")
        logging.info(
            f"[{self.consumer_name}] 即将推送 AI 简报 degraded={degraded} "
            f"chars={len(markdown)}:\n{markdown}"
        )
        ok = self.wechat_notifier.send_text(markdown)
        if ok:
            logging.info(f"[{self.consumer_name}] AI 简报推送成功 degraded={degraded}")
        else:
            logging.error(f"[{self.consumer_name}] AI 简报推送失败 degraded={degraded}")

    def _handle_market_briefing(self, message: BaseMessage):
        markdown = message.payload.get("markdown", "")
        hit = message.payload.get("hit_count")
        total = message.payload.get("row_count")
        logging.info(
            f"[{self.consumer_name}] 即将推送行情早报 hit={hit}/{total} "
            f"chars={len(markdown)}:\n{markdown}"
        )
        if not markdown:
            logging.warning(f"[{self.consumer_name}] 行情早报为空，跳过")
            return
        ok = self.wechat_notifier.send_text(markdown)
        if ok:
            logging.info(f"[{self.consumer_name}] 行情早报推送成功 hit={hit}/{total}")
        else:
            logging.error(f"[{self.consumer_name}] 行情早报推送失败 hit={hit}/{total}")
