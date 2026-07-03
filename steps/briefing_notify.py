import logging
from typing import Any

from steps.notify_base import BaseNotifyStep
from models.messages import AIBriefingMessage
from notifiers.wechat_notifier import WeChatNotifier
from config.social import X_BRIEFING_WEBHOOK_URLS
from config.morning_briefing import MORNING_WEBHOOK_URLS


class BriefingNotifyStep(BaseNotifyStep):
    """AI 简报推送。"""

    def __init__(self, notifier: WeChatNotifier | None = None, name: str = "BriefingNotifyStep"):
        super().__init__(notifier=notifier, name=name)

    async def process(self, data: Any) -> None:
        if data is None:
            return None

        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, AIBriefingMessage):
                self._send_one(item)

        return None

    def _send_one(self, message: AIBriefingMessage):
        markdown = message.payload.get("markdown", "")
        degraded = message.payload.get("degraded")
        logging.info(f"[{self.name}] 推送 AI 简报 degraded={degraded} chars={len(markdown)}")
        ok = self.notifier.send_text(markdown)
        if ok:
            logging.info(f"[{self.name}] AI 简报推送成功")
        else:
            logging.error(f"[{self.name}] AI 简报推送失败")


class XBriefingNotifyStep(BriefingNotifyStep):
    def __init__(self):
        super().__init__(
            notifier=WeChatNotifier(X_BRIEFING_WEBHOOK_URLS or None),
            name="XBriefingNotifyStep",
        )


class MorningBriefingNotifyStep(BriefingNotifyStep):
    def __init__(self):
        super().__init__(
            notifier=WeChatNotifier(MORNING_WEBHOOK_URLS or None),
            name="MorningBriefingNotifyStep",
        )
