"""Cursor Cloud Agents 请求路径。不打真实 API。"""
import asyncio

import pytest

from clients.llm_client import BriefingInput, CursorLLMClient, client_from_config
from models.social import SocialPost


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = str(payload)
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, timeout=None, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url}")
        return self.responses.pop(0)


def _payload():
    post = SocialPost(
        post_id="1",
        author="sama",
        author_name="Sam",
        text="hello",
        created_at="2026-10-13T00:00:00Z",
        url="https://x.com/sama/status/1",
    )
    return BriefingInput(posts=[post], window_hours=24, max_chars=3000)


def _client(session, **kwargs):
    options = dict(
        api_key="test-key",
        model="composer-2.5",
        prompt_template="窗口 {window_hours} 上限 {max_chars}\n{posts_block}",
        timeout_sec=5,
        poll_interval_sec=0,
        session=session,
    )
    options.update(kwargs)
    return CursorLLMClient(**options)


def test_summarize_returns_finished_text_and_usage():
    session = FakeSession([
        FakeResponse({
            "agent": {"id": "bc-1", "url": "https://cursor.com/agents/bc-1"},
            "run": {"id": "run-1", "status": "CREATING"},
        }),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "hello world"}),
        FakeResponse({
            "runs": [{
                "id": "run-1",
                "usage": {"inputTokens": 11, "outputTokens": 2},
            }],
        }),
    ])
    result = asyncio.run(_client(session).summarize(_payload()))

    assert result.markdown == "hello world"
    assert result.model == "composer-2.5"
    assert result.input_tokens == 11
    assert result.output_tokens == 2
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/v1/agents")
    assert "repos" not in kwargs["json"]
    assert kwargs["json"]["model"] == {"id": "composer-2.5"}
    assert kwargs["json"]["prompt"]["text"].startswith("窗口 24 上限 3000")
    assert session.calls[2][0] == "GET"
    assert session.calls[2][2]["params"] == {"runId": "run-1"}


def test_run_error_raises():
    session = FakeSession([
        FakeResponse({
            "agent": {"id": "bc-1"},
            "run": {"id": "run-1", "status": "RUNNING"},
        }),
        FakeResponse({"id": "run-1", "status": "ERROR", "result": "boom"}),
    ])
    with pytest.raises(RuntimeError, match="ERROR"):
        asyncio.run(_client(session).summarize(_payload()))


def test_create_4xx_does_not_retry():
    session = FakeSession([
        FakeResponse({"error": "unauthorized"}, status=401),
        FakeResponse({"error": "should-not-retry"}, status=401),
    ])
    with pytest.raises(RuntimeError, match="create failed"):
        asyncio.run(_client(session).summarize(_payload()))
    assert [call[0] for call in session.calls] == ["POST"]


def test_missing_api_key():
    client = _client(FakeSession([]), api_key="")
    with pytest.raises(RuntimeError, match="CURSOR_API_KEY"):
        asyncio.run(client.summarize(_payload()))


def test_client_from_config_selects_cursor():
    client = client_from_config({
        "name": "cursor",
        "api_key": "k",
        "base_url": "https://api.cursor.com",
        "model": "composer-2.5",
        "timeout_sec": 30,
        "poll_interval_sec": 1,
    }, "tpl {window_hours} {max_chars} {posts_block}")
    assert isinstance(client, CursorLLMClient)
    assert client.model == "composer-2.5"
    assert client.base_url == "https://api.cursor.com"
