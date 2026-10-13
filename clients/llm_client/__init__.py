"""LLM 边界。后端由 config.social._LLM_PROVIDER 选择：tongyi 或 cursor。"""
from clients.llm_client.base import (
    BriefingInput,
    BriefingOutput,
    LLMClient,
    render_briefing_prompt,
)
from clients.llm_client.cursor import CursorLLMClient
from clients.llm_client.factory import (
    build_default_llm_client,
    build_llm_client,
    build_morning_llm_client,
    client_from_config,
)
from clients.llm_client.tongyi import TongyiLLMClient

__all__ = [
    "BriefingInput",
    "BriefingOutput",
    "CursorLLMClient",
    "LLMClient",
    "TongyiLLMClient",
    "build_default_llm_client",
    "build_llm_client",
    "build_morning_llm_client",
    "client_from_config",
    "render_briefing_prompt",
]
