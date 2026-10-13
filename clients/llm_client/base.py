"""LLM 协议与简报入出参。业务代码只依赖 LLMClient。"""
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

from models.social import SocialPost


@dataclass
class BriefingInput:
    posts: List[SocialPost]
    window_hours: int
    max_chars: int
    extra_context: str = ""


@dataclass
class BriefingOutput:
    markdown: str
    sections: List[Dict[str, Any]]   # [{topic, summary, post_ids}]
    model: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    async def summarize(self, payload: BriefingInput) -> BriefingOutput: ...


def render_briefing_prompt(prompt_template: str, payload: BriefingInput) -> str:
    # 全局按时间正序（旧→新）：跨账号同主题事件相邻出现，便于 LLM 主题聚合；
    # 最新事件落在 prompt 尾部，对齐 LLM 的 recency bias。
    # created_at 是 ISO8601 字符串，词典序与时间序一致；空串排最前不影响。
    ordered = sorted(payload.posts, key=lambda p: p.created_at or "")
    posts_block = "\n\n".join(
        f"[{p.author}] {p.created_at}\n{p.text}\n{p.url}"
        for p in ordered
    )
    kwargs = dict(
        window_hours=payload.window_hours,
        max_chars=payload.max_chars,
        posts_block=posts_block,
    )
    if payload.extra_context:
        kwargs["market_block"] = payload.extra_context
    return prompt_template.format(**kwargs)
