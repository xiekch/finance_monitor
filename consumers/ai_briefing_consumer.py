import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from consumers.base_consumer import BaseConsumer
from infra.message_queue import mq
from models.messages import (
    MessageType,
    SocialPostBatchMessage,
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
    def __init__(self, llm: Optional[LLMClient] = None):
        super().__init__("AIBriefingConsumer", [MessageType.SOCIAL_POST_BATCH])
        self.llm = llm or build_default_llm_client()

    def process_message(self, message: Dict):
        batch = SocialPostBatchMessage.from_dict(message)
        posts = [SocialPost.from_dict(p) for p in batch.payload.get("posts", [])]
        if not posts:
            logging.warning(f"[{self.consumer_name}] empty batch received, skip")
            return

        bi = BriefingInput(
            posts=posts,
            window_hours=batch.payload.get("window_hours", SOCIAL_CONFIG["window_hours"]),
            user_prompt_extra=SOCIAL_CONFIG.get("user_prompt_extra"),
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
            logging.error(f"[{self.consumer_name}] LLM summarize failed: {e}", exc_info=True)
            by_author = batch.payload.get("stats", {}).get("by_author", {})
            md = (
                f"📰 AI 简报生成失败\n\n"
                f"收到 {len(posts)} 条推文（{by_author}）\n"
                f"错误: {e}\n\n"
                f"原始推文 ID 已写入 SQLite social_posts 表。"
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
        mq.publish(MessageType.AI_BRIEFING.value, out.to_dict())
        logging.info(
            f"[{self.consumer_name}] published AI_BRIEFING degraded={payload['degraded']} "
            f"posts={len(posts)}"
        )
