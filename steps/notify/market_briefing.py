import logging

from steps.notify.base import BaseNotifyStep
from models.market import MarketBriefing
from clients.wechat_notifier import WeChatNotifier
from config.morning_briefing import MORNING_WEBHOOK_URLS


class MarketBriefingNotifyStep(BaseNotifyStep):
    """标的行情早报推送。"""

    def __init__(self):
        super().__init__(
            notifier=WeChatNotifier(MORNING_WEBHOOK_URLS or None),
            name="MarketBriefingNotifyStep",
        )

    async def process(self, items: list) -> list:
        for item in items:
            if isinstance(item, MarketBriefing):
                self._send_one(item)
        return []

    def _send_one(self, briefing: MarketBriefing):
        markdown = briefing.markdown
        if not markdown:
            logging.warning(f"[{self.name}] 行情早报为空，跳过")
            return
        logging.info(f"[{self.name}] 推送行情早报 chars={len(markdown)}")
        ok = self.notifier.send_markdown(markdown)
        if ok:
            logging.info(f"[{self.name}] 行情早报推送成功")
        else:
            logging.error(f"[{self.name}] 行情早报推送失败")
