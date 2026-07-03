import logging
from datetime import date as _date

from steps.notify.base import BaseNotifyStep
from models.market import VolatilityAlert
from clients.wechat_notifier import WeChatNotifier


class VolatilityNotifyStep(BaseNotifyStep):
    """波动告警推送：daily/weekly 同日同标的去重。"""

    _DEDUP_FREQUENCIES = frozenset({"daily", "weekly"})

    def __init__(self, notifier: WeChatNotifier | None = None):
        super().__init__(notifier=notifier, name="VolatilityNotifyStep")
        self._alerted_keys: set[tuple[str, str, _date]] = set()

    async def process(self, items: list) -> list:
        for item in items:
            if isinstance(item, VolatilityAlert):
                self._send_one(item)
        return []

    def _send_one(self, alert: VolatilityAlert):
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
