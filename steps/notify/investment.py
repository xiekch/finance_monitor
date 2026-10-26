import logging

from clients.wechat_notifier import WeChatNotifier
from config.investment import DISCLAIMER
from models.advice import InvestmentMessage
from steps.notify.base import BaseNotifyStep


class InvestmentNotifyStep(BaseNotifyStep):
    """投资建议与复盘推送：每条消息单独发 markdown，空列表不发。"""

    def __init__(self, notifier: WeChatNotifier | None = None):
        super().__init__(notifier=notifier, name="InvestmentNotifyStep")

    async def process(self, items: list) -> list:
        for item in items:
            if not isinstance(item, InvestmentMessage):
                continue
            ok = self.notifier.send_markdown(f"{item.markdown}\n\n{DISCLAIMER}")
            if not ok:
                logging.error(f"[{self.name}] 推送失败")
        return []
