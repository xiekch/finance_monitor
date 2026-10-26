import asyncio

import pytest

from clients.llm_client.cursor import CursorLLMClient
from clients.llm_client.factory import build_investment_llm_client
from config.social import SOCIAL_CONFIG


def test_cursor_complete_sends_prompt_without_briefing_template(monkeypatch):
    client = CursorLLMClient(api_key="k", model="grok-4.7", prompt_template="UNUSED {posts_block}")
    seen = {}

    def fake_create_and_wait(prompt: str):
        seen["prompt"] = prompt
        return "agent", {"id": "run", "result": " NO_NEW_FINDING \n"}

    monkeypatch.setattr(client, "_create_and_wait", fake_create_and_wait)
    monkeypatch.setattr(client, "_fetch_usage", lambda agent_id, run_id: (0, 0))
    assert asyncio.run(client.complete("请搜索 NVDA 现价")) == "NO_NEW_FINDING"
    assert seen["prompt"] == "请搜索 NVDA 现价"


def test_create_agent_sends_repos_only_when_configured(monkeypatch):
    bodies = []

    def fake_get_json(url, method="GET", **kwargs):
        bodies.append(kwargs.get("json"))
        return {"agent": {"id": "a"}, "run": {"id": "r", "status": "FINISHED"}}

    plain = CursorLLMClient(api_key="k", model="m", prompt_template="")
    monkeypatch.setattr(plain, "_get_json", fake_get_json)
    plain._create_agent("p")
    repo = {"url": "https://github.com/xiekch/finance_monitor", "startingRef": "main"}
    mounted = CursorLLMClient(api_key="k", model="m", prompt_template="", repos=[repo])
    monkeypatch.setattr(mounted, "_get_json", fake_get_json)
    mounted._create_agent("p")
    assert "repos" not in bodies[0]
    assert bodies[1]["repos"] == [repo]


def test_investment_client_requires_cursor_and_mounts_repo(monkeypatch):
    monkeypatch.setitem(SOCIAL_CONFIG, "llm_provider", {
        "name": "cursor", "api_key": "k", "base_url": "https://api.cursor.com",
        "model": "grok-4.7", "timeout_sec": 900,
    })
    client = build_investment_llm_client()
    assert isinstance(client, CursorLLMClient)
    assert client.repos == [{"url": "https://github.com/xiekch/finance_monitor", "startingRef": "main"}]
    assert client.timeout_sec == 1500
    assert SOCIAL_CONFIG["llm_provider"]["timeout_sec"] == 900
    monkeypatch.setitem(SOCIAL_CONFIG, "llm_provider", {"name": "tongyi"})
    with pytest.raises(RuntimeError, match="搜索"):
        build_investment_llm_client()
