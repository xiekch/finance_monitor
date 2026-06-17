"""X 推文 / AI 简报的数据模型。"""
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any


@dataclass
class SocialPost:
    post_id: str          # 平台内唯一；跨平台去重靠 (platform, post_id)
    author: str           # @handle（不带 @）或微博 screen_name
    author_name: str
    text: str
    created_at: str       # UTC ISO8601 字符串
    url: str
    is_retweet: bool = False
    referenced_url: Optional[str] = None
    platform: str = "x"   # "x" | "weibo"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SocialPost":
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**d)


@dataclass
class Briefing:
    created_at: str          # UTC ISO8601
    window_hours: int
    source_post_ids: List[str]
    markdown: str
    sections_json: str       # 结构化 sections，json.dumps 后存
    model: str
    input_tokens: int
    output_tokens: int
    degraded: bool
    error: Optional[str]
    source: str = ""         # 来源 producer/consumer 名称，区分 x_briefing vs morning_briefing
