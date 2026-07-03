import logging
from datetime import date as _date, datetime
from typing import Any

from steps.notify_base import BaseNotifyStep
from models.messages import BaseMessage, MessageType, VolatilityAlertMessage
from models.market import VolatilityAlert
from notifiers.wechat_notifier import WeChatNotifier


class VolatilityNotifyStep(BaseNotifyStep):
    """波动告警推送：daily/weekly 同日同标的去重。"""

    _DEDUP_FREQUENCIES = frozenset({"daily", "weekly"})

    def __init__(self, notifier: WeChatNotifier | None = None):
        super().__init__(notifier=notifier, name="VolatilityNotifyStep")
        self._alerted_keys: set[tuple[str, str, _date]] = set()

    async def process(self, data: Any) -> None:
        if data is None:
            return None

        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, VolatilityAlertMessage):
                self._send_one(item)
            elif isinstance(item, BaseMessage) and item.message_type == MessageType.VOLATILITY_ALERT:
                self._send_one(item)

        return None

    def _send_one(self, message: BaseMessage):
        alert_data = message.payload
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
            if key in self._alerted_keys:
                logging.info(
                    f"[{self.name}] 告警当天已推送，跳过: "
                    f"{alert.name}({alert.symbol}) {alert.frequency}"
                )
                return
            self._alerted_keys.add(key)

        if self.notifier.send_alert(alert):
            logging.info(f"[{self.name}] 告警通知发送成功: {alert.name}")
        else:
            logging.error(f"[{self.name}] 告警通知发送失败: {alert.name}")
