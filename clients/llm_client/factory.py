"""按 SOCIAL_CONFIG.llm_provider.name 选择具体客户端。"""
from typing import Any, Dict

from clients.llm_client.base import LLMClient
from clients.llm_client.cursor import CursorLLMClient
from clients.llm_client.tongyi import TongyiLLMClient


def build_llm_client(prompt_template: str) -> LLMClient:
    from config.social import SOCIAL_CONFIG
    return client_from_config(SOCIAL_CONFIG["llm_provider"], prompt_template)


def client_from_config(llm_cfg: Dict[str, Any], prompt_template: str) -> LLMClient:
    name = llm_cfg.get("name", "tongyi")
    if name == "cursor":
        return CursorLLMClient(
            api_key=llm_cfg["api_key"],
            base_url=llm_cfg["base_url"],
            model=llm_cfg["model"],
            prompt_template=prompt_template,
            timeout_sec=llm_cfg["timeout_sec"],
            poll_interval_sec=llm_cfg.get("poll_interval_sec", 3),
        )
    if name != "tongyi":
        raise RuntimeError(f"unknown llm provider: {name}")
    return TongyiLLMClient(
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        model=llm_cfg["model"],
        max_tokens=llm_cfg["max_tokens"],
        temperature=llm_cfg.get("temperature", 0.3),
        prompt_template=prompt_template,
        timeout_sec=llm_cfg["timeout_sec"],
        enable_thinking=llm_cfg.get("enable_thinking"),
    )


def build_default_llm_client() -> LLMClient:
    from config.social import SOCIAL_CONFIG
    return build_llm_client(SOCIAL_CONFIG["prompt_template"])


def build_morning_llm_client() -> LLMClient:
    from config.morning_briefing import MORNING_BRIEFING_CONFIG
    return build_llm_client(MORNING_BRIEFING_CONFIG["prompt_template"])


def build_investment_llm_client() -> CursorLLMClient:
    """投资建议要联网搜索并读仓库里的 advice/，只有 cursor 后端满足。"""
    from config.investment import ADVICE_REPO_REF, ADVICE_REPO_URL
    from config.social import SOCIAL_CONFIG
    cfg = SOCIAL_CONFIG["llm_provider"]
    if cfg.get("name") != "cursor":
        raise RuntimeError("投资建议需要能联网搜索的后端，当前只支持 cursor")
    client = client_from_config(cfg, "")
    client.repos = [{"url": ADVICE_REPO_URL, "startingRef": ADVICE_REPO_REF}]
    return client
