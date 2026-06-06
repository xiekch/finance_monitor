import asyncio
import logging
from datetime import datetime
from typing import Optional

from consumers.base_consumer import BaseConsumer
from infra.message_queue import mq
from models.messages import (
    BaseMessage,
    MessageType,
    AIBriefingMessage,
)
from clients.llm_client import (
    LLMClient,
    BriefingInput,
    build_default_llm_client,
)
from models.social import SocialPost
from config.social import SOCIAL_CONFIG


class AIBriefingConsumer(BaseConsumer):
    """收到各平台的 SOCIAL_POST_BATCH 后，在内存聚合帖子。

    收齐 ``expected_platforms`` 中所有平台的 batch 后，一次性调 LLM
    生成混合简报。如果只启用一个平台，则收到即触发，与旧行为一致。
    """

    def __init__(
        self,
        expected_platforms: Optional[set[str]] = None,
        llm: Optional[LLMClient] = None,
    ):
        super().__init__("AIBriefingConsumer", [MessageType.SOCIAL_POST_BATCH])
        self.llm = llm or build_default_llm_client()
        self.expected_platforms: set[str] = expected_platforms or {"x"}
        self._received: set[str] = set()
        self._buffer: list[SocialPost] = []

    def process_message(self, message: BaseMessage):
        posts = [SocialPost.from_dict(p) for p in message.payload.get("posts", [])]
        platform = message.payload.get("platform", "x")

        self._buffer.extend(posts)
        self._received.add(platform)

        logging.info(
            f"[{self.consumer_name}] received batch platform={platform} "
            f"posts={len(posts)} received={self._received} "
            f"expected={self.expected_platforms}"
        )

        if self._received >= self.expected_platforms:
            self._generate_briefing()
        else:
            pending = self.expected_platforms - self._received
            logging.info(
                f"[{self.consumer_name}] 等待其他平台: {pending}"
            )

    def _generate_briefing(self):
        posts = self._buffer
        self._buffer = []
        self._received.clear()

        if not posts:
            logging.warning(f"[{self.consumer_name}] buffer empty, skip")
            return

        bi = BriefingInput(
            posts=posts,
            window_hours=SOCIAL_CONFIG["window_hours"],
            max_chars=SOCIAL_CONFIG["push_max_chars"],
        )

        try:
            result = asyncio.run(self.llm.summarize(bi))
            payload = {
                "markdown": result.markdown,
                "sections": result.sections,
                "source_post_count": len(posts),
                "source_post_ids": [p.post_id for p in posts],
                "stats": {
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                "degraded": False,
                "error": None,
                "created_at": datetime.now().isoformat(),
                "window_hours": bi.window_hours,
            }
        except Exception as e:
            logging.error(
                f"[{self.consumer_name}] LLM summarize failed: {e}",
                exc_info=True,
            )
            md = (
                f"📰 AI 简报生成失败\n\n"
                f"收到 {len(posts)} 条帖子\n"
                f"错误: {e}\n\n"
                f"原始帖子 ID 已写入 SQLite social_posts 表。"
            )
            payload = {
                "markdown": md,
                "sections": [],
                "source_post_count": len(posts),
                "source_post_ids": [p.post_id for p in posts],
                "stats": {},
                "degraded": True,
                "error": str(e),
                "created_at": datetime.now().isoformat(),
                "window_hours": bi.window_hours,
            }

        out = AIBriefingMessage(payload=payload, source=self.consumer_name)
        mq.publish(MessageType.AI_BRIEFING.value, out)
        logging.info(
            f"[{self.consumer_name}] published AI_BRIEFING degraded={payload['degraded']} "
            f"posts={len(posts)}"
        )
