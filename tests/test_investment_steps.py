import asyncio
from datetime import date
from pathlib import Path

from config.investment import DISCLAIMER
from models.advice import parse_advice_markdown
from steps.investment_advice import AdviceStep
from steps.investment_review import ReviewStep
from steps.notify.investment import InvestmentNotifyStep
from storage.advice_store import AdviceStore


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_markdown(self, content: str) -> bool:
        self.sent.append(content)
        return True


class FakeCommitter:
    def __init__(self, ok=True, error=None):
        self.messages = []
        self.ok = ok
        self.last_error = None
        self._error = error

    def commit(self, message: str) -> bool:
        self.messages.append(message)
        self.last_error = self._error
        return self.ok


def _run(step, notifier):
    items = asyncio.run(step.process([]))
    asyncio.run(InvestmentNotifyStep(notifier=notifier).process(items))


ADVICE = """# 建议 1
- symbol: NVDA
- name: 英伟达
- direction: 看多
- expiry_date: 2026-11-09
- currency: USD
- reference_price: 140
- reference_date: 2026-10-26
- reference_url: https://example.com/nvda
- target_price: 160

## 理由
需求还在。

## 目标价
160 附近。

## 失效条件
跌破 120。

## 参考价
140 收盘。

## 观察条件
财报。
"""

DUE = """## 复盘 2026-10-28 到期结案
- 价格：建议时 140，目标价 160，结案时 151。未碰到目标价。来源 https://example.com/close
- 逻辑：需求仍在。
- 事件过程：订单评论偏多。
- 经验：没碰到目标价就不要写成已兑现。
"""

WEEKLY = """## 复盘 2026-10-26 周回溯
- 价格：碰到失效价。
- 逻辑：催化剂落空。
- 事件过程：订单下修。
- 经验：无
"""


def test_advice_step_saves_commits_and_pushes(tmp_path: Path):
    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM([ADVICE]), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert (tmp_path / "2026-10" / "2026-10-26-1.md").is_file()
    assert committer.messages == ["advice: 2026-10-26 新增 英伟达 看多"]
    assert len(notifier.sent) == 1
    assert "NVDA" in notifier.sent[0]
    assert notifier.sent[0].rstrip().endswith(DISCLAIMER)


def test_advice_failure_pushes_error_and_writes_nothing(tmp_path: Path):
    class Boom:
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("down")

    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = AdviceStep(store_root=tmp_path, llm=Boom(), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert list(tmp_path.rglob("*.md")) == []
    assert committer.messages == []
    assert notifier.sent and "失败" in notifier.sent[0]


def test_commit_failure_still_pushes_with_note(tmp_path: Path):
    notifier = FakeNotifier()
    committer = FakeCommitter(ok=True, error="推送失败：rejected")
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM([ADVICE]), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert "NVDA" in notifier.sent[0]
    assert "推送失败" in notifier.sent[-1]


def test_weekly_silent_on_no_new_finding(tmp_path: Path, advice_md):
    AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(19)))
    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = ReviewStep(kind="weekly", store_root=tmp_path, llm=FakeLLM(["NO_NEW_FINDING"]),
                      committer=committer, today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert notifier.sent == []
    assert committer.messages == []


def test_due_uses_today_at_run_time_and_closes(tmp_path: Path, advice_md):
    saved = AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(25, expiry=date(2026, 10, 27))))
    days = [date(2026, 10, 26)]
    llm = FakeLLM([DUE])
    committer = FakeCommitter()
    step = ReviewStep(kind="due", store_root=tmp_path, llm=llm, committer=committer,
                      today_fn=lambda: days[0])
    notifier = FakeNotifier()
    _run(step, notifier)
    assert llm.prompts == [] and notifier.sent == [] and committer.messages == []
    days[0] = date(2026, 10, 28)
    _run(step, notifier)
    text = (tmp_path / "2026-10" / f"{saved.id}.md").read_text(encoding="utf-8")
    assert "status: closed" in text
    assert committer.messages == ["advice: 2026-10-28 到期结案 测试标的 看多"]
    assert len(notifier.sent) == 1


def test_review_cap_skips_extra_files(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    store.save_new(parse_advice_markdown(advice_md(19)))
    store.save_new(parse_advice_markdown(advice_md(20, symbol="AAPL")))
    llm = FakeLLM([WEEKLY])
    notifier = FakeNotifier()
    step = ReviewStep(kind="weekly", store_root=tmp_path, llm=llm, committer=FakeCommitter(),
                      max_per_run=1, today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert len(llm.prompts) == 1
    assert "跳过 1 份" in notifier.sent[-1]
