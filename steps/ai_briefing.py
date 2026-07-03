import json
import logging
from typing import List

from steps.base import Step
from models.social import SocialPost, Briefing
from clients.llm_client import LLMClient, BriefingInput, build_default_llm_client
from config.social import SOCIAL_CONFIG
from utils.time_util import utc_now_iso


class AIBriefingStep(Step):
    """从聚合后的社交帖子生成 AI 简报。

    输入：list[SocialPost]（来自 FetchMultiSource 或单平台 fetch 步骤）
    输出：list[Briefing]
    """

    def __init__(self, llm: LLMClient | None = None):
        self.name = "AIBriefingStep"
        self.llm = llm or build_default_llm_client()

    async def process(self, items: list) -> List[Briefing]:
        posts = [x for x in items if isinstance(x, SocialPost)]
        if not posts:
            logging.warning(f"[{self.name}] 无帖子，跳过生成")
            return []

        bi = BriefingInput(
            posts=posts,
            window_hours=SOCIAL_CONFIG["window_hours"],
            max_chars=SOCIAL_CONFIG["push_max_chars"],
        )

        try:
            result = await self.llm.summarize(bi)
            briefing = Briefing(
                created_at=utc_now_iso(),
                window_hours=bi.window_hours,
                source_post_ids=[p.post_id for p in posts],
                markdown=result.markdown,
                sections_json=json.dumps(result.sections),
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                degraded=False,
                error=None,
                source=self.name,
            )
        except Exception as e:
            logging.error(f"[{self.name}] LLM summarize failed: {e}", exc_info=True)
            md = (
                f"📰 AI 简报生成失败\n\n"
                f"收到 {len(posts)} 条帖子\n"
                f"错误: {e}\n\n"
                f"原始帖子 ID 已写入 SQLite social_posts 表。"
            )
            briefing = Briefing(
                created_at=utc_now_iso(),
                window_hours=SOCIAL_CONFIG["window_hours"],
                source_post_ids=[p.post_id for p in posts],
                markdown=md,
                sections_json="[]",
                model="",
                input_tokens=0,
                output_tokens=0,
                degraded=True,
                error=str(e),
                source=self.name,
            )

        return [briefing]
