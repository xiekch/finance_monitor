"""Cursor Cloud Agents 请求路径。不打真实 API。"""
import asyncio

import pytest
import requests

from clients.llm_client import BriefingInput, CursorLLMClient, client_from_config
from clients.llm_client.cursor import (
    _HTTP_TIMEOUT,
    _POLL_CONNECT_TIMEOUT,
    _POLL_MAX_ATTEMPTS,
    _POLL_READ_TIMEOUT,
)
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
        self.timeouts = []

    def request(self, method, url, timeout=None, **kwargs):
        self.calls.append((method, url, kwargs))
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


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


def _running_then(*poll_items):
    return [
        FakeResponse({
            "agent": {"id": "bc-1", "url": "https://cursor.com/agents/bc-1"},
            "run": {"id": "run-1", "status": "RUNNING"},
        }),
        *poll_items,
    ]


def _no_sleep(monkeypatch):
    monkeypatch.setattr("clients.llm_client.cursor.time.sleep", lambda _seconds: None)


def test_poll_get_uses_longer_timeout_than_create(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession(_running_then(
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "ok"}),
        FakeResponse({"runs": [{"usage": {"inputTokens": 1, "outputTokens": 1}}]}),
    ))
    result = asyncio.run(_client(session, timeout_sec=900).summarize(_payload()))

    assert result.markdown == "ok"
    assert session.timeouts[0] == _HTTP_TIMEOUT
    assert session.timeouts[1] == (_POLL_CONNECT_TIMEOUT, _POLL_READ_TIMEOUT)
    assert session.timeouts[2] == _HTTP_TIMEOUT
    assert session.calls[1][0] == "GET"
    assert session.calls[1][1].endswith("/v1/agents/bc-1/runs/run-1")


def test_poll_retries_read_timeout_and_connection_error(monkeypatch):
    slept = []
    monkeypatch.setattr(
        "clients.llm_client.cursor.time.sleep",
        lambda seconds: slept.append(seconds),
    )
    session = FakeSession(_running_then(
        requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)"),
        requests.exceptions.ConnectionError("connection reset"),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "recovered"}),
        FakeResponse({"runs": [{"usage": {"inputTokens": 3, "outputTokens": 4}}]}),
    ))
    result = asyncio.run(_client(session, timeout_sec=900).summarize(_payload()))

    assert result.markdown == "recovered"
    assert result.input_tokens == 3
    assert [call[0] for call in session.calls] == ["POST", "GET", "GET", "GET", "GET"]
    assert slept == [0, 1.0, 2.0]
    assert session.timeouts[1:4] == [(_POLL_CONNECT_TIMEOUT, _POLL_READ_TIMEOUT)] * 3


@pytest.mark.parametrize("status", [502, 503, 504])
def test_poll_retries_gateway_status(status, monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession(_running_then(
        FakeResponse({"error": "unavailable"}, status=status),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "after gateway"}),
        FakeResponse({"runs": []}),
    ))
    result = asyncio.run(_client(session, timeout_sec=900).summarize(_payload()))

    assert result.markdown == "after gateway"
    assert [call[0] for call in session.calls] == ["POST", "GET", "GET", "GET"]


def test_poll_does_not_retry_other_http_errors(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession(_running_then(
        FakeResponse({"error": "boom"}, status=500),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "should-not-run"}),
    ))
    with pytest.raises(requests.HTTPError, match="500"):
        asyncio.run(_client(session, timeout_sec=900).summarize(_payload()))
    assert [call[0] for call in session.calls] == ["POST", "GET"]


def test_poll_raises_after_retry_budget(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession(_running_then(
        *([requests.exceptions.ReadTimeout("slow")] * _POLL_MAX_ATTEMPTS),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "too late"}),
    ))
    with pytest.raises(requests.exceptions.ReadTimeout):
        asyncio.run(_client(session, timeout_sec=900).summarize(_payload()))
    assert [call[0] for call in session.calls] == ["POST", "GET", "GET", "GET"]


def test_poll_does_not_retry_after_overall_deadline(monkeypatch):
    class Clock:
        def __init__(self):
            self.now = 1_000_000.0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr("clients.llm_client.cursor.time.time", clock.time)
    monkeypatch.setattr("clients.llm_client.cursor.time.sleep", clock.sleep)

    class ExpiringSession(FakeSession):
        def request(self, method, url, timeout=None, **kwargs):
            self.calls.append((method, url, kwargs))
            self.timeouts.append(timeout)
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                clock.now += 10_000
                raise item
            return item

    session = ExpiringSession(_running_then(
        requests.exceptions.ReadTimeout("slow"),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "should-not-poll"}),
    ))
    with pytest.raises(requests.exceptions.ReadTimeout):
        asyncio.run(_client(session, timeout_sec=5).summarize(_payload()))
    assert [call[0] for call in session.calls] == ["POST", "GET"]


def test_poll_backoff_stops_at_deadline(monkeypatch):
    class Clock:
        def __init__(self):
            self.now = 1_000_000.0
            self.slept = []

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr("clients.llm_client.cursor.time.time", clock.time)
    monkeypatch.setattr("clients.llm_client.cursor.time.sleep", clock.sleep)
    session = FakeSession(_running_then(
        *([requests.exceptions.ReadTimeout("slow")] * _POLL_MAX_ATTEMPTS),
    ))
    with pytest.raises(requests.exceptions.ReadTimeout):
        asyncio.run(_client(session, timeout_sec=1.5, poll_interval_sec=0).summarize(_payload()))

    # 间隔 0，第一次失败后 backoff 1s，第二次被剩余预算截成 0.5s，不再发第三次。
    assert clock.slept == [0, 1.0, 0.5]
    assert [call[0] for call in session.calls] == ["POST", "GET", "GET"]
    deadline = 1_000_000.0 + 1.5
    assert clock.now == pytest.approx(deadline)
    assert session.timeouts[1][1] == pytest.approx(1.5)
    assert session.timeouts[2][1] == pytest.approx(0.5)


def test_poll_retry_log_omits_api_key(monkeypatch, caplog):
    _no_sleep(monkeypatch)
    session = FakeSession(_running_then(
        requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)"),
        FakeResponse({"id": "run-1", "status": "FINISHED", "result": "ok"}),
        FakeResponse({"runs": []}),
    ))
    with caplog.at_level("WARNING"):
        asyncio.run(_client(session, api_key="super-secret-key", timeout_sec=900).summarize(_payload()))
    assert "super-secret-key" not in caplog.text
    assert "poll agent=bc-1" in caplog.text


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
