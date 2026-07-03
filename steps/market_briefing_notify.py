import logging
from typing import Any

from steps.notify_base import BaseNotifyStep
from models.messages import MarketBriefingMessage
from notifiers.wechat_notifier import WeChatNotifier
from config.morning_briefing import MORNING_WEBHOOK_URLS


class MarketBriefingNotifyStep(BaseNotifyStep):
    """标的行情早报推送。"""

    def __init__(self):
        super().__init__(
            notifier=WeChatNotifier(MORNING_WEBHOOK_URLS or None),
            name="MarketBriefingNotifyStep",
        )

    async def process(self, data: Any) -> None:
        if data is None:
            return None

        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, MarketBriefingMessage):
                self._send_one(item)

        return None

    def _send_one(self, message: MarketBriefingMessage):
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
