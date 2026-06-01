"""LLM 边界。业务代码只依赖 LLMClient 协议。默认实现走阿里百炼 (ChatTongyi)。"""
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, Dict, Any

from models.social import SocialPost


@dataclass
class BriefingInput:
    posts: List[SocialPost]
    window_hours: int
    user_prompt_extra: Optional[str]
    max_chars: int


@dataclass
class BriefingOutput:
    markdown: str
    sections: List[Dict[str, Any]]   # [{topic, summary, post_ids}]
    model: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    async def summarize(self, payload: BriefingInput) -> BriefingOutput: ...


class TongyiLLMClient:
    """默认实现：通过 OpenAI 兼容协议调阿里百炼 (DashScope)。

    走 langchain_openai.ChatOpenAI + base_url 指向 DashScope 的
    /compatible-mode/v1 端点；比 langchain_community.ChatTongyi
    省去 deprecated warning、key 字段别名不透传等坑，且能直接拿
    到标准 usage_metadata。
    """

    def __init__(self, api_key: str, model: str, max_tokens: int,
                 prompt_template: str, base_url: str,
                 temperature: float = 0.3, timeout_sec: int = 60):
        from langchain_openai import ChatOpenAI
        self._llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_sec,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_sec = timeout_sec
        self.prompt_template = prompt_template

    async def summarize(self, payload: BriefingInput) -> BriefingOutput:
        from langchain_core.messages import HumanMessage
        prompt = self._render_prompt(payload)
        logging.info(
            f"[TongyiLLMClient] invoking model={self.model} "
            f"posts={len(payload.posts)} prompt_chars={len(prompt)}"
        )
        last_err: Optional[Exception] = None
        for attempt in range(2):
            t0 = time.time()
            try:
                resp = self._llm.invoke([HumanMessage(content=prompt)])
                ms = int((time.time() - t0) * 1000)
                in_tok, out_tok = self._extract_token_usage(resp)
                markdown = (resp.content or "").strip()
                logging.info(
                    f"[TongyiLLMClient] model={self.model} "
                    f"in={in_tok} out={out_tok} elapsed={ms}ms output_chars={len(markdown)}"
                )
                logging.info(f"[TongyiLLMClient] output markdown:\n{markdown}")
                return BriefingOutput(
                    markdown=markdown,
                    sections=[],   # MVP 不强制结构化解析
                    model=self.model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
            except Exception as e:
                last_err = e
                wait = 1.0 * (2 ** attempt)
                logging.warning(
                    f"[TongyiLLMClient] attempt {attempt + 1} failed: {e}; retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"LLM summarize failed: {last_err}")

    @staticmethod
    def _extract_token_usage(resp) -> "tuple[int, int]":
        """langchain 在不同版本下 token 字段位置不同，做几个兜底。"""
        # langchain >= 0.2: AIMessage.usage_metadata
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        # 部分版本只在 response_metadata.token_usage
        rmeta = getattr(resp, "response_metadata", {}) or {}
        tu = rmeta.get("token_usage") or {}
        return int(tu.get("input_tokens", 0) or tu.get("prompt_tokens", 0)), \
               int(tu.get("output_tokens", 0) or tu.get("completion_tokens", 0))

    def _render_prompt(self, payload: BriefingInput) -> str:
        posts_block = "\n\n".join(
            f"[{p.author}] {p.created_at}\n{p.text}\n{p.url}"
            for p in payload.posts
        )
        return self.prompt_template.format(
            window_hours=payload.window_hours,
            user_prompt_extra=payload.user_prompt_extra or "",
            max_chars=payload.max_chars,
            posts_block=posts_block,
        )


def build_default_llm_client() -> LLMClient:
    import os
    from config.social import SOCIAL_CONFIG
    llm_cfg = SOCIAL_CONFIG["llm_provider"]
    return TongyiLLMClient(
        api_key=os.getenv(llm_cfg["api_key_env"], ""),
        base_url=llm_cfg["base_url"],
        model=llm_cfg["model"],
        max_tokens=llm_cfg["max_tokens"],
        temperature=llm_cfg.get("temperature", 0.3),
        prompt_template=SOCIAL_CONFIG["prompt_template"],
        timeout_sec=llm_cfg["timeout_sec"],
    )
