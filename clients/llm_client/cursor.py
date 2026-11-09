"""Cursor Cloud Agents REST。不经过本机 Cursor 应用。"""
import logging
import time
from typing import Optional

import requests

from clients.llm_client.base import BriefingInput, BriefingOutput, render_briefing_prompt


_TERMINAL_STATUSES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}

# 创建 agent、拉 usage 仍用较短超时。轮询 run 状态单独放宽：
# api.cursor.com 偶发 read stall，而整体等待预算是 timeout_sec（常见 900s）。
# 单次 GET 若 30s 无响应且不重试，会在 agent 仍在跑时提前失败。
_HTTP_TIMEOUT = 30
_POLL_CONNECT_TIMEOUT = 10
_POLL_READ_TIMEOUT = 90
_POLL_MAX_ATTEMPTS = 3
_POLL_BACKOFF_BASE_SEC = 1.0
_RETRYABLE_POLL_STATUS = frozenset({502, 503, 504})


class CursorLLMClient:
    """创建 agent（默认无仓库），轮询 run，取最终文本。"""

    def __init__(self, api_key: str, model: str, prompt_template: str,
                 base_url: str = "https://api.cursor.com",
                 timeout_sec: int = 300, poll_interval_sec: float = 3,
                 session: Optional[requests.Session] = None,
                 repos: Optional[list] = None):
        self.api_key = api_key
        self.model = model
        self.prompt_template = prompt_template
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.poll_interval_sec = poll_interval_sec
        self.session = session or self._new_session(api_key)
        self.repos = repos

    @staticmethod
    def _new_session(api_key: str) -> requests.Session:
        session = requests.Session()
        # Basic auth：用户名是 API key，密码为空。等价于 curl -u "$KEY:"。
        session.auth = (api_key, "")
        session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        return session

    async def summarize(self, payload: BriefingInput) -> BriefingOutput:
        if not self.api_key:
            raise RuntimeError("CURSOR_API_KEY 未配置")
        prompt = render_briefing_prompt(self.prompt_template, payload)
        logging.info(
            f"[CursorLLMClient] invoking model={self.model} "
            f"posts={len(payload.posts)} prompt_chars={len(prompt)}"
        )
        logging.info(f"[CursorLLMClient] prompt:\n{prompt}")
        t0 = time.time()
        agent_id, run = self._create_and_wait(prompt)
        markdown = (run.get("result") or "").strip()
        in_tok, out_tok = self._fetch_usage(agent_id, run["id"])
        ms = int((time.time() - t0) * 1000)
        logging.info(
            f"[CursorLLMClient] model={self.model} agent={agent_id} run={run['id']} "
            f"in={in_tok} out={out_tok} elapsed={ms}ms output_chars={len(markdown)}"
        )
        logging.info(f"[CursorLLMClient] output markdown:\n{markdown}")
        return BriefingOutput(
            markdown=markdown,
            sections=[],
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    async def complete(self, prompt: str) -> str:
        """发送完整提示词，返回 agent 的最终文本。"""
        if not self.api_key:
            raise RuntimeError("CURSOR_API_KEY 未配置")
        logging.info(
            f"[CursorLLMClient] complete model={self.model} repos={bool(self.repos)} "
            f"prompt_chars={len(prompt)}"
        )
        logging.info(f"[CursorLLMClient] prompt:\n{prompt}")
        t0 = time.time()
        agent_id, run = self._create_and_wait(prompt)
        text = (run.get("result") or "").strip()
        in_tok, out_tok = self._fetch_usage(agent_id, run["id"])
        ms = int((time.time() - t0) * 1000)
        logging.info(
            f"[CursorLLMClient] model={self.model} agent={agent_id} run={run['id']} "
            f"in={in_tok} out={out_tok} elapsed={ms}ms output_chars={len(text)}"
        )
        logging.info(f"[CursorLLMClient] output:\n{text}")
        return text

    def _create_and_wait(self, prompt: str) -> "tuple[str, dict]":
        created = self._create_agent(prompt)
        agent = created["agent"]
        run = created["run"]
        agent_id = agent["id"]
        run_id = run["id"]
        logging.info(
            f"[CursorLLMClient] created agent={agent_id} run={run_id} url={agent.get('url', '')}"
        )
        deadline = time.time() + self.timeout_sec
        while run.get("status") not in _TERMINAL_STATUSES:
            if time.time() > deadline:
                raise RuntimeError(
                    f"Cursor run timed out: agent={agent_id} run={run_id} status={run.get('status')}"
                )
            time.sleep(self.poll_interval_sec)
            run = self._poll_run(agent_id, run_id, deadline)
        if run.get("status") != "FINISHED":
            raise RuntimeError(
                f"Cursor run {run.get('status')}: agent={agent_id} run={run_id} "
                f"result={run.get('result') or ''}"
            )
        return agent_id, run

    def _create_agent(self, prompt: str) -> dict:
        url = f"{self.base_url}/v1/agents"
        body = {
            "name": "finance-monitor",
            "prompt": {"text": prompt},
            "model": {"id": self.model},
        }
        if self.repos:
            body["repos"] = self.repos
        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                return self._get_json(url, method="POST", json=body)
            except Exception as e:
                last_err = e
                # 4xx 是参数或鉴权问题，重试只会再创建一个 agent 或再次失败。
                if _is_client_error(e) or attempt == 1:
                    break
                wait = 1.0 * (2 ** attempt)
                logging.warning(
                    f"[CursorLLMClient] create attempt {attempt + 1} failed: {e}; retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"Cursor agent create failed: {last_err}")

    def _poll_run(self, agent_id: str, run_id: str, deadline: float) -> dict:
        """轮询一次 run。慢响应和 502/503/504 在整体 deadline 内重试几次。"""
        url = f"{self.base_url}/v1/agents/{agent_id}/runs/{run_id}"
        last_err: Optional[Exception] = None
        for attempt in range(_POLL_MAX_ATTEMPTS):
            timeout = _poll_http_timeout(deadline)
            if timeout is None:
                break
            try:
                return self._get_json(url, timeout=timeout)
            except Exception as e:
                last_err = e
                if not _is_retryable_poll_error(e) or attempt + 1 >= _POLL_MAX_ATTEMPTS:
                    raise
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise
                wait = min(_POLL_BACKOFF_BASE_SEC * (2 ** attempt), remaining)
                logging.warning(
                    f"[CursorLLMClient] poll agent={agent_id} run={run_id} "
                    f"attempt {attempt + 1}/{_POLL_MAX_ATTEMPTS} failed: {e}; "
                    f"retry in {wait:.1f}s"
                )
                time.sleep(wait)
        if last_err is not None:
            raise last_err
        raise RuntimeError(
            f"Cursor run timed out: agent={agent_id} run={run_id}"
        )

    def _fetch_usage(self, agent_id: str, run_id: str) -> "tuple[int, int]":
        try:
            data = self._get_json(
                f"{self.base_url}/v1/agents/{agent_id}/usage",
                params={"runId": run_id},
            )
        except Exception as e:
            logging.warning(f"[CursorLLMClient] usage fetch failed: {e}")
            return 0, 0
        runs = data.get("runs") or []
        usage = (runs[0].get("usage") if runs else None) or data.get("totalUsage") or {}
        return int(usage.get("inputTokens") or 0), int(usage.get("outputTokens") or 0)

    def _get_json(self, url: str, method: str = "GET", timeout=_HTTP_TIMEOUT, **kwargs) -> dict:
        resp = self.session.request(method, url, timeout=timeout, **kwargs)
        if not resp.ok:
            detail = (resp.text or "")[:500]
            raise requests.HTTPError(
                f"Cursor API {resp.status_code} {method} {url}: {detail}",
                response=resp,
            )
        return resp.json()


def _poll_http_timeout(deadline: float):
    """返回 (connect, read)。剩余预算不够时缩短，预算用尽则不再发请求。"""
    remaining = deadline - time.time()
    if remaining <= 0:
        return None
    read = min(_POLL_READ_TIMEOUT, remaining)
    return (min(_POLL_CONNECT_TIMEOUT, read), read)


def _is_retryable_poll_error(err: Exception) -> bool:
    if isinstance(err, (requests.Timeout, requests.ConnectionError)):
        return True
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    return status in _RETRYABLE_POLL_STATUS


def _is_client_error(err: Exception) -> bool:
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500
