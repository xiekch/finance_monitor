"""阿里百炼 OpenAI 兼容接口。"""
import logging
import time
from typing import Optional

from clients.llm_client.base import BriefingInput, BriefingOutput, render_briefing_prompt


class TongyiLLMClient:
    """通过 langchain_openai.ChatOpenAI 调 DashScope /compatible-mode/v1。

    比 langchain_community.ChatTongyi 少 deprecated warning 和 key 字段别名问题，
    且能直接拿到标准 usage_metadata。
    """

    def __init__(self, api_key: str, model: str, max_tokens: int,
                 prompt_template: str, base_url: str,
                 temperature: float = 0.3, timeout_sec: int = 60,
                 enable_thinking: Optional[bool] = None):
        """
        Args:
            enable_thinking: DashScope 扩展字段，控制 qwen3 系列是否走 thinking 模式。
                - None：不传该字段，沿用模型默认（qwen3 默认 True）
                - True/False：显式开启/关闭
                deepseek 等不支持该字段的模型会忽略它。
        """
        from langchain_openai import ChatOpenAI
        extra_body = {"enable_thinking": enable_thinking} if enable_thinking is not None else None
        self._llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_sec,
            extra_body=extra_body,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_sec = timeout_sec
        self.prompt_template = prompt_template
        self.enable_thinking = enable_thinking

    async def summarize(self, payload: BriefingInput) -> BriefingOutput:
        from langchain_core.messages import HumanMessage
        prompt = self._render_prompt(payload)
        logging.info(
            f"[TongyiLLMClient] invoking model={self.model} "
            f"posts={len(payload.posts)} prompt_chars={len(prompt)}"
        )
        logging.info(f"[TongyiLLMClient] prompt:\n{prompt}")
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
        return render_briefing_prompt(self.prompt_template, payload)
