import logging

from clients.wechat_notifier import WeChatNotifier
from config.holdings import HOLDINGS_WEBHOOK_URLS
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


class HoldingsNotifyStep(InvestmentNotifyStep):
    """持仓日报推送：配置了 HOLDINGS_WEBHOOK_URL 就发到专用群，否则用默认 webhook。"""

    def __init__(self, notifier: WeChatNotifier | None = None):
        super().__init__(notifier=notifier or WeChatNotifier(HOLDINGS_WEBHOOK_URLS or None))
        self.name = "HoldingsNotifyStep"
