import logging
from datetime import date as _date, datetime
from typing import Any

from steps.base import Step
from models.messages import (
    BaseMessage,
    MessageType,
    VolatilityAlertMessage,
    AIBriefingMessage,
    MarketBriefingMessage,
)
from notifiers.wechat_notifier import WeChatNotifier


class NotifyStep(Step):
    """推送通知（终端步骤）。

    支持：VolatilityAlertMessage / AIBriefingMessage / MarketBriefingMessage，
    也支持 list 形式的输入。返回 None 终止链路。
    """

    _DEDUP_FREQUENCIES = frozenset({"daily", "weekly"})

    def __init__(self, notifier: WeChatNotifier | None = None):
        self.name = "NotifyStep"
        self.notifier = notifier or WeChatNotifier()
        self._alerted_keys: set[tuple[str, str, _date]] = set()

    async def process(self, data: Any) -> None:
        if data is None:
            return None

        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, VolatilityAlertMessage):
                self._handle_volatility_alert(item)
            elif isinstance(item, AIBriefingMessage):
                self._handle_briefing(item)
            elif isinstance(item, MarketBriefingMessage):
                self._handle_market_briefing(item)
            elif isinstance(item, BaseMessage) and item.message_type == MessageType.VOLATILITY_ALERT:
                self._handle_volatility_alert(item)

        return None

    def _handle_volatility_alert(self, message: BaseMessage):
        from models.market import VolatilityAlert

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

    def _handle_briefing(self, message: BaseMessage):
        markdown = message.payload.get("markdown", "")
        degraded = message.payload.get("degraded")
        logging.info(f"[{self.name}] 推送 AI 简报 degraded={degraded} chars={len(markdown)}")
        ok = self.notifier.send_text(markdown)
        if ok:
            logging.info(f"[{self.name}] AI 简报推送成功")
        else:
            logging.error(f"[{self.name}] AI 简报推送失败")

    def _handle_market_briefing(self, message: BaseMessage):
        markdown = message.payload.get("markdown", "")
        if not markdown:
            logging.warning(f"[{self.name}] 行情早报为空，跳过")
            return
        hit = message.payload.get("hit_count")
        total = message.payload.get("row_count")
        logging.info(f"[{self.name}] 推送行情早报 hit={hit}/{total} chars={len(markdown)}")
        ok = self.notifier.send_text(markdown)
        if ok:
            logging.info(f"[{self.name}] 行情早报推送成功")
        else:
            logging.error(f"[{self.name}] 行情早报推送失败")
