import logging

from clients.wechat_notifier import WeChatNotifier
from config.new_stock import NEW_STOCK_WEBHOOK_URLS
from models.market import NewStockListing
from steps.notify.base import BaseNotifyStep


def format_new_stock_message(listings: list[NewStockListing]) -> str:
    day = listings[0].listing_date
    lines = [f"## 🆕 今日新股上市（{day.isoformat()}）共 {len(listings)} 只", ""]
    for s in listings:
        place = s.exchange if s.board in ("", s.exchange) else f"{s.exchange} {s.board}"
        head = f"**{s.name}**（{s.symbol}）{place}".rstrip()
        details = []
        if s.issue_price is not None:
            details.append(f"发行价 {s.issue_price:.2f} 元")
        if s.issue_pe is not None:
            pe = f"发行市盈率 {s.issue_pe:.2f}"
            if s.industry_pe is not None:
                pe += f"（行业 {s.industry_pe:.2f}）"
            details.append(pe)
        if s.issue_shares is not None:
            details.append(f"发行 {s.issue_shares:.0f} 万股")
        if s.subscribe_date is not None:
            details.append(f"申购日 {s.subscribe_date.isoformat()}")
        lines.append(f"- {head}")
        if details:
            lines.append(f"  {'，'.join(details)}")
    return "\n".join(lines)


class NewStockNotifyStep(BaseNotifyStep):
    """新股上市推送：有上市的才发，今天没有就静默。

    配置了 NEW_STOCK_WEBHOOK_URL 就发到专用群，否则用默认 webhook。
    """

    def __init__(self, notifier: WeChatNotifier | None = None):
        super().__init__(
            notifier=notifier or WeChatNotifier(NEW_STOCK_WEBHOOK_URLS or None),
            name="NewStockNotifyStep",
        )

    async def process(self, items: list) -> list:
        listings = [i for i in items if isinstance(i, NewStockListing)]
        if not listings:
            logging.info(f"[{self.name}] 今天没有新股上市，不推送")
            return []
        ok = self.notifier.send_markdown(format_new_stock_message(listings))
        if ok:
            logging.info(f"[{self.name}] 新股上市推送成功，{len(listings)} 只")
        else:
            logging.error(f"[{self.name}] 新股上市推送失败")
        return []
