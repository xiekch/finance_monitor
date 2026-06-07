import logging
from datetime import datetime
from typing import Any

from steps.base import Step
from models.messages import SocialPostBatchMessage, AIBriefingMessage
from models.social import SocialPost
from clients.llm_client import LLMClient, BriefingInput, build_default_llm_client
from config.social import SOCIAL_CONFIG


class AIBriefingStep(Step):
    """从聚合后的社交帖子生成 AI 简报。

    输入：list[SocialPostBatchMessage]（来自 FetchMultiSource）或单个 SocialPostBatchMessage
    输出：AIBriefingMessage
    """

    def __init__(self, llm: LLMClient | None = None):
        self.name = "AIBriefingStep"
        self.llm = llm or build_default_llm_client()

    async def process(self, data: Any) -> AIBriefingMessage | None:
        posts = self._extract_posts(data)
        if not posts:
            logging.warning(f"[{self.name}] 无帖子，跳过生成")
            return None

        bi = BriefingInput(
            posts=posts,
            window_hours=SOCIAL_CONFIG["window_hours"],
            max_chars=SOCIAL_CONFIG["push_max_chars"],
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
                "created_at": datetime.now().isoformat(),
                "window_hours": bi.window_hours,
            }
        except Exception as e:
            logging.error(f"[{self.name}] LLM summarize failed: {e}", exc_info=True)
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
                "window_hours": SOCIAL_CONFIG["window_hours"],
            }

        return AIBriefingMessage(payload=payload, source=self.name)

    @staticmethod
    def _extract_posts(data: Any) -> list[SocialPost]:
        if data is None:
            return []
        items = data if isinstance(data, list) else [data]
        posts: list[SocialPost] = []
        for item in items:
            if isinstance(item, SocialPostBatchMessage):
                posts.extend(
                    SocialPost.from_dict(p) for p in item.payload.get("posts", [])
                )
        return posts
