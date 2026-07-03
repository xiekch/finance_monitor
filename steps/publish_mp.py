import logging
from datetime import datetime

import markdown

from steps.base import Step
from models.social import Briefing
from clients.wechat_mp_client import WechatMPClient


class PublishMPStep(Step):
    """将 AI 早报发布到微信公众号（草稿 → 发布）。

    未配置 AppID/AppSecret 时静默跳过，不影响 Fork 中的其他分支。
    """

    def __init__(self):
        self.name = "PublishMPStep"
        self.client = WechatMPClient()
        self._md = markdown.Markdown(extensions=["tables", "fenced_code"])

    async def process(self, items: list) -> list:
        if not self.client.configured:
            logging.warning(f"[{self.name}] 未配置 WECHAT_MP_APP_ID/SECRET，跳过公众号发布")
            return []

        briefing = next((x for x in items if isinstance(x, Briefing)), None)
        if briefing is None:
            logging.warning(f"[{self.name}] 未收到 Briefing，跳过")
            return []

        md_text = briefing.markdown
        if not md_text:
            logging.warning(f"[{self.name}] markdown 内容为空，跳过")
            return []

        title = f"AI 早报 {datetime.now().strftime('%Y-%m-%d')}"
        content_html = self._md.convert(md_text)
        self._md.reset()

        try:
            media_id = self.client.add_draft(title=title, content_html=content_html)
            publish_id = self.client.publish(media_id)
            logging.info(
                f"[{self.name}] 公众号发布成功 title={title} "
                f"media_id={media_id} publish_id={publish_id}"
            )
        except Exception as e:
            logging.error(f"[{self.name}] 公众号发布失败: {e}", exc_info=True)

        return []
