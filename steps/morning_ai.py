import json
import logging
from typing import List

from steps.base import Step
from models.social import MorningData, Briefing
from clients.llm_client import BriefingInput, build_morning_llm_client
from config.morning_briefing import MORNING_BRIEFING_CONFIG
from utils.time_util import utc_now_iso


class MorningAIStep(Step):
    """从早报原料（社交帖子 + 行情块）生成 AI 早报。

    输入：list[MorningData]
    输出：list[Briefing]
    """

    def __init__(self):
        self.name = "MorningAIStep"
        self.llm = build_morning_llm_client()
        self.cfg = MORNING_BRIEFING_CONFIG

    async def process(self, items: list) -> List[Briefing]:
        data = next((x for x in items if isinstance(x, MorningData)), None)
        if data is None:
            return []

        posts = data.posts
        window_hours = data.window_hours

        bi = BriefingInput(
            posts=posts,
            window_hours=window_hours,
            max_chars=self.cfg["push_max_chars"],
            extra_context=data.market_block,
        )

        try:
            result = await self.llm.summarize(bi)
            briefing = Briefing(
                created_at=utc_now_iso(),
                window_hours=window_hours,
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
            logging.error(f"[{self.name}] LLM 生成失败: {e}", exc_info=True)
            md = (
                f"📰 AI 早报生成失败\n\n"
                f"收到 {len(posts)} 条帖子\n"
                f"错误: {e}\n\n"
                f"原始帖子已写入 SQLite social_posts 表。"
            )
            briefing = Briefing(
                created_at=utc_now_iso(),
                window_hours=window_hours,
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
