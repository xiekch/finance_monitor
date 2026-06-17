import logging
from typing import Any

from steps.base import Step
from models.messages import AIBriefingMessage
from clients.llm_client import BriefingInput, build_morning_llm_client
from config.morning_briefing import MORNING_BRIEFING_CONFIG
from utils.time_util import utc_now_iso


class MorningAIStep(Step):

    def __init__(self):
        self.name = "MorningAIStep"
        self.llm = build_morning_llm_client()
        self.cfg = MORNING_BRIEFING_CONFIG

    async def process(self, data: Any) -> AIBriefingMessage | None:
        if not data:
            return None

        posts = data["posts"]
        market_block = data["market_block"]
        window_hours = data["window_hours"]

        bi = BriefingInput(
            posts=posts,
            window_hours=window_hours,
            max_chars=self.cfg["push_max_chars"],
            extra_context=market_block,
        )

        try:
            result = await self.llm.summarize(bi)
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
                "created_at": utc_now_iso(),
                "window_hours": window_hours,
            }
        except Exception as e:
            logging.error(f"[{self.name}] LLM 生成失败: {e}", exc_info=True)
            md = (
                f"📰 AI 早报生成失败\n\n"
                f"收到 {len(posts)} 条帖子\n"
                f"错误: {e}\n\n"
                f"原始帖子已写入 SQLite social_posts 表。"
            )
            payload = {
                "markdown": md,
                "sections": [],
                "source_post_count": len(posts),
                "source_post_ids": [p.post_id for p in posts],
                "stats": {},
                "degraded": True,
                "error": str(e),
                "created_at": utc_now_iso(),
                "window_hours": window_hours,
            }

        return AIBriefingMessage(payload=payload, source=self.name)
