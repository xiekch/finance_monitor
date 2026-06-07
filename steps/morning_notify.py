from steps.notify import NotifyStep
from notifiers.wechat_notifier import WeChatNotifier
from config.morning_briefing import MORNING_WEBHOOK_URLS


class MorningNotifyStep(NotifyStep):

    def __init__(self):
        super().__init__(WeChatNotifier(MORNING_WEBHOOK_URLS or None))
        self.name = "MorningNotifyStep"
