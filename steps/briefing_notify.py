import logging

from steps.notify_base import BaseNotifyStep
from models.social import Briefing
from notifiers.wechat_notifier import WeChatNotifier
from config.social import X_BRIEFING_WEBHOOK_URLS
from config.morning_briefing import MORNING_WEBHOOK_URLS


class BriefingNotifyStep(BaseNotifyStep):
    """AI 简报推送。"""

    def __init__(self, notifier: WeChatNotifier | None = None, name: str = "BriefingNotifyStep"):
        super().__init__(notifier=notifier, name=name)

    async def process(self, items: list) -> list:
        for item in items:
            if isinstance(item, Briefing):
                self._send_one(item)
        return []

    def _send_one(self, briefing: Briefing):
        markdown = briefing.markdown
        logging.info(
            f"[{self.name}] 推送 AI 简报 degraded={briefing.degraded} chars={len(markdown)}"
        )
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
