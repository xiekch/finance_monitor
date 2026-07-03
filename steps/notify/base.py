from steps.base import Step
from clients.wechat_notifier import WeChatNotifier


class BaseNotifyStep(Step):
    """推送终端步骤基类，持有通用 WeChatNotifier。"""

    def __init__(
        self,
        notifier: WeChatNotifier | None = None,
        name: str = "NotifyStep",
    ):
        self.name = name
        self.notifier = notifier or WeChatNotifier()
