import asyncio
from datetime import date
from pathlib import Path

from config.investment import DISCLAIMER
from fetchers.price_history import DailyBar
from models.advice import parse_advice_markdown
from steps.investment_advice import AdviceStep, format_advice_message
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
- summary: 需求没走弱，财报前看多
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
- 结论：➖ 没碰到目标价，等待没有结果
- 价格：建议时 140，目标价 160，结案时 151。未碰到目标价。来源 https://example.com/close
- 逻辑：需求仍在。
- 事件过程：订单评论偏多。
- 经验：没碰到目标价就不要写成已兑现。
"""

WEEKLY = """## 复盘 2026-10-26 周回溯
- 结论：❌ 碰到失效价，催化剂落空
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


def test_advice_message_inlines_full_sections(advice_md):
    doc = parse_advice_markdown(advice_md())
    doc.id = "2026-10-26-1"
    doc.sections["理由"] = "需求还在。订单排到明年。"
    text = format_advice_message(doc)
    assert "需求没走弱，财报前看多" in text
    assert "需求还在。订单排到明年。" in text
    assert "失效条件" in text and "观察条件" in text
    assert "github.com" not in text
    assert "查看全文" not in text


def test_advice_message_without_summary_still_has_sections(advice_md):
    doc = parse_advice_markdown(advice_md())
    doc.id, doc.summary = "2026-10-26-1", ""
    doc.sections["理由"] = "需求还在。订单排到明年。"
    text = format_advice_message(doc)
    assert "需求还在。订单排到明年。" in text
    assert text.startswith("**投资建议")


def test_advice_message_shows_sided_watch(advice_md):
    doc = parse_advice_markdown(advice_md(direction="观望偏空", target_price=150, stop_price=130))
    doc.id = "2026-10-26-2"
    text = format_advice_message(doc)
    assert "观望偏空" in text
    assert "观望偏多" not in text


def test_no_advice_is_silent_and_writes_nothing(tmp_path: Path):
    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM(["NO_ADVICE\n没有新的催化剂。"]),
                      committer=committer, today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert list(tmp_path.rglob("*.md")) == []
    assert committer.messages == []
    assert notifier.sent == []


def test_garbage_answer_is_still_reported_as_failure(tmp_path: Path):
    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM(["今天没有建议"]), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert committer.messages == []
    assert notifier.sent and "生成失败" in notifier.sent[0]


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


def _bars_fn(bars, calls=None):
    def fn(symbol, start, end):
        if calls is not None:
            calls.append((symbol, start, end))
        return bars
    return fn


NVDA_BARS = [
    DailyBar(date(2026, 10, 26), 141, 145, 138, 142),
    DailyBar(date(2026, 10, 27), 150, 161, 141, 160),   # 最高 161，盘中碰到目标价 160
]


def test_review_prompt_carries_program_facts_and_price_line_is_overwritten(tmp_path: Path, advice_md):
    saved = AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(25, expiry=date(2026, 10, 27))))
    llm, calls = FakeLLM([DUE]), []   # DUE 里模型自己写的价格行是「未碰到目标价」，和事实矛盾
    step = ReviewStep(kind="due", store_root=tmp_path, llm=llm, committer=FakeCommitter(),
                      today_fn=lambda: date(2026, 10, 28), bars_fn=_bars_fn(NVDA_BARS, calls))
    _run(step, FakeNotifier())

    assert calls == [("NVDA", date(2026, 10, 25), date(2026, 10, 27))]
    prompt = llm.prompts[0]
    assert "程序从日 K 算出的事实" in prompt
    assert "目标价 160（高于参考价 140）：10/27盘中碰到" in prompt
    assert "程序没有取到" not in prompt

    text = (tmp_path / "2026-10" / f"{saved.id}.md").read_text(encoding="utf-8")
    price = next(line for line in text.splitlines() if line.startswith("- 价格："))
    assert "目标价10/27盘中碰到" in price and "最高 161（10/27）" in price
    assert "未碰到目标价" not in text and "https://example.com/close" not in price
    assert "- 逻辑：需求仍在。" in text            # 其余行保持模型写的


def test_review_without_program_prices_falls_back_to_model(tmp_path: Path, advice_md):
    saved = AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(25, expiry=date(2026, 10, 27))))
    llm = FakeLLM([DUE])
    step = ReviewStep(kind="due", store_root=tmp_path, llm=llm, committer=FakeCommitter(),
                      today_fn=lambda: date(2026, 10, 28),
                      bars_fn=lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))   # 接口异常
    asyncio.run(step.process([]))
    assert "程序没有取到这只标的的行情" in llm.prompts[0]
    text = (tmp_path / "2026-10" / f"{saved.id}.md").read_text(encoding="utf-8")
    assert "未碰到目标价。来源 https://example.com/close" in text   # 模型的价格行原样保留


def test_new_advice_with_wrong_reference_price_is_dropped(tmp_path: Path):
    committer, notifier, calls = FakeCommitter(), FakeNotifier(), []
    wrong = [DailyBar(date(2026, 10, 26), 99, 102, 98, 100)]     # 模型写的参考价 140，实际收 100
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM([ADVICE]), committer=committer,
                      today_fn=lambda: date(2026, 10, 26), bars_fn=_bars_fn(wrong, calls))
    _run(step, notifier)
    assert calls == [("NVDA", date(2026, 10, 19), date(2026, 10, 26))]
    assert list(tmp_path.rglob("*.md")) == [] and committer.messages == []
    assert notifier.sent and "没有合法建议，丢弃 1 条" in notifier.sent[0]


def test_new_advice_is_kept_when_price_fetch_raises(tmp_path: Path):
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM([ADVICE]), committer=FakeCommitter(),
                      today_fn=lambda: date(2026, 10, 26),
                      bars_fn=lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    _run(step, FakeNotifier())
    assert (tmp_path / "2026-10" / "2026-10-26-1.md").is_file()


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


LONG_DUE = """## 复盘 2026-10-28 到期结案
- 结论：❌ 没做对：10/27 盘中碰到失效价 120，之后收 118
- 价格：建议时 140，失效价 120，结案时 118（https://example.com/close）。10/27 盘中碰到失效价。
- 逻辑：订单下修，当初的需求逻辑没有兑现。
- 事件过程：10/26 开 139 收 138；10/27 开 130 低 119 收 121；10/28 收 118。https://example.com/day
- 经验：失效价被碰到就认错，不要等反弹。
"""


def test_due_push_shows_conclusion_and_key_points_only(tmp_path: Path, advice_md):
    AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(25, expiry=date(2026, 10, 27))))
    notifier = FakeNotifier()
    step = ReviewStep(kind="due", store_root=tmp_path, llm=FakeLLM([LONG_DUE]),
                      committer=FakeCommitter(), today_fn=lambda: date(2026, 10, 28))
    _run(step, notifier)
    text = notifier.sent[0]
    body = text.split("\n", 1)[1]
    assert body.startswith("**❌ 没做对：10/27 盘中碰到失效价 120，之后收 118**")
    assert "价格：建议时 140，失效价 120，结案时 118。" in text
    assert "逻辑：订单下修" in text
    assert "经验：失效价被碰到就认错" in text
    assert "事件过程" not in text and "10/26 开 139" not in text
    assert "http" not in text


def test_push_skips_empty_lesson_and_keeps_legacy_reviews(tmp_path: Path, advice_md):
    from steps.investment_review import format_review_message

    doc = parse_advice_markdown(advice_md(25))
    doc.id = "2026-10-26-1"
    doc.reviews = [LONG_DUE.replace("- 经验：失效价被碰到就认错，不要等反弹。", "- 经验：无")]
    assert "经验" not in format_review_message(doc, "到期结案").split("\n", 1)[1]

    legacy = "## 复盘 2026-10-28 到期结案\n- 价格：旧格式。\n- 逻辑：旧逻辑。\n- 事件过程：旧过程。\n- 经验：旧经验。"
    doc.reviews = [legacy]
    text = format_review_message(doc, "到期结案")
    assert "- 事件过程：旧过程。" in text and "- 价格：旧格式。" in text


def test_review_without_conclusion_is_rejected():
    import pytest
    from models.advice import check_review_note

    note = "## 复盘 2026-10-28 到期结案\n- 价格：x\n- 逻辑：y\n- 事件过程：z\n- 经验：无\n"
    with pytest.raises(ValueError, match="结论"):
        check_review_note(note, "due")
