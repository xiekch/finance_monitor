import asyncio
import json
from datetime import date

import pytest

from analyzers.portfolio import PriceQuote
from config.investment import DISCLAIMER
from steps.holdings_advice import HoldingsAdviceStep
from steps.notify.investment import HoldingsNotifyStep

TODAY = date(2026, 11, 15)

# 成本：茅台 50000、腾讯 100×100×0.9 = 9000、英伟达 20×100×7 = 14000，现金 27000，合计 100000
CONFIG = """
[cash]
CNY = 27000

[rules]
max_position_pct = 40

[[holdings]]
symbol = "600519"
market = "SH"
name = "贵州茅台"
quantity = 100
cost = 500
thesis = "高端白酒龙头"

[[holdings]]
symbol = "00700"
market = "HK"
name = "腾讯控股"
quantity = 100
cost = 100

[[holdings]]
symbol = "NVDA"
market = "US"
name = "英伟达"
quantity = 20
cost = 100
"""


def _block(symbol, name, action, *, basis="无新变化", summary="", target=""):
    fields = [f"- action: {action}"]
    if target:
        fields.append(f"- target_weight: {target}")
    if summary:
        fields.append(f"- summary: {summary}")
    return (
        f"# {symbol} {name}\n" + "\n".join(fields) + "\n\n"
        f"## 依据\n{basis}\n\n## 执行\n执行说明 {symbol}。\n\n"
        f"## 风险\n风险说明。\n\n## 什么情况下改变结论\n改变条件。\n"
    )


PORTFOLIO = "# 组合\n\n## 整体判断\n白酒占比偏高。\n\n## 今天最该处理的一件事\n减茅台。\n"

DAY = date(2026, 11, 13)
# 市值：茅台 45000、腾讯 18000、英伟达 21000，加现金 27000 = 111000
QUOTES = {
    "600519": PriceQuote(450.0, DAY, "新浪行情"),
    "00700": PriceQuote(200.0, DAY, "新浪行情"),
    "NVDA": PriceQuote(150.0, DAY, "新浪行情"),
}
MAOTAI_TRIM = _block(
    "600519", "贵州茅台", "减仓", summary="动销走弱，反弹减仓", target="30-35",
    basis="11 月 12 日下调全年目标（https://example.com/notice）。",
)
TENCENT_HOLD = _block("00700", "腾讯控股", "持有", summary="游戏流水稳定")
NVDA_HOLD = _block("NVDA", "英伟达", "持有")
DAY1 = "\n".join([MAOTAI_TRIM, TENCENT_HOLD, NVDA_HOLD, PORTFOLIO])


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_markdown(self, content: str) -> bool:
        self.sent.append(content)
        return True


async def _fx(currencies):
    rates = {"CNY": 1.0, "USD": 7.0, "HKD": 0.9}
    return {c: rates[c] for c in currencies if c in rates}


@pytest.fixture
def env(tmp_path):
    config = tmp_path / "holdings.toml"
    config.write_text(CONFIG, encoding="utf-8")

    def make(answers, *, today=TODAY, fx=_fx, quotes=QUOTES):
        clock = {"today": today}
        llm = FakeLLM(answers)

        async def quote_fetcher(holdings, day):
            if isinstance(quotes, Exception):
                raise quotes
            return {h.symbol: quotes[h.symbol] for h in holdings if h.symbol in quotes}

        step = HoldingsAdviceStep(
            config_path=config, report_root=tmp_path / "reports",
            advice_root=tmp_path / "advice", llm=llm, fx_fetcher=fx,
            quote_fetcher=quote_fetcher, today_fn=lambda: clock["today"],
        )
        return step, llm, clock

    make.config = config
    make.reports = tmp_path / "reports"
    make.advice = tmp_path / "advice"
    return make


def _run(step):
    notifier = FakeNotifier()
    items = asyncio.run(step.process([]))
    asyncio.run(HoldingsNotifyStep(notifier=notifier).process(items))
    return notifier.sent


def test_full_run_pushes_ratios_and_keeps_amounts_local(env):
    step, llm, _ = env([DAY1])
    sent = _run(step)

    assert len(llm.prompts) == 1
    # 总览 + 茅台详情（减仓）+ 组合；持有且无变化的不发详情
    assert len(sent) == 3
    overview, detail, portfolio = sent
    assert overview.startswith("**持仓日报 2026-11-15**")
    assert "浮动盈亏 +15.1%" in overview and "现金 24.3%" in overview
    assert "人民币 64.9%" in overview and "美元 18.9%" in overview and "港币 16.2%" in overview
    assert "**减仓** 600519 贵州茅台｜占比 40.5% · 盈亏 -10.0%" in overview
    assert "> 动销走弱，反弹减仓" in overview
    assert "**持有** 00700 腾讯控股｜占比 16.2% · 盈亏 +100.0%" in overview
    assert "**持有** NVDA 英伟达｜占比 18.9% · 盈亏 +50.0%" in overview
    assert "超出规则：贵州茅台 占比 40.5%，超过单个持仓上限 40%" in overview
    assert "上次" not in overview

    assert detail.startswith("**600519 贵州茅台｜减仓**")
    assert "现价 450 CNY（2026-11-13） · 盈亏 -10.0%" in detail
    assert "盈亏 -10.0%" in detail and "占比 40.5% → 目标 30-35%" in detail
    assert "**依据**\n11 月 12 日下调全年目标" in detail
    assert "**执行**" in detail and "**什么情况下改变结论**" in detail

    assert portfolio.startswith("**组合**")
    assert "**今天最该处理的一件事**\n减茅台。" in portfolio

    for text in sent:
        assert text.rstrip().endswith(DISCLAIMER)
        for amount in ("45000", "45,000", "111000", "111,000", "27000", "27,000"):
            assert amount not in text

    report = (env.reports / "2026-11-15.md").read_text(encoding="utf-8")
    assert "111,000.00" in report and "45,000.00" in report and "-5,000.00" in report
    assert "USD 7" in report and "HKD 0.9" in report
    assert "新浪行情" in report
    assert "## 模型回复原文" in report and "# 600519 贵州茅台" in report
    saved = json.loads((env.reports / "2026-11-15.json").read_text(encoding="utf-8"))
    assert saved == {"date": "2026-11-15",
                     "actions": {"600519": "减仓", "00700": "持有", "NVDA": "持有"}}


def test_prompt_has_program_prices_but_never_amounts(env):
    step, llm, _ = env([DAY1])
    _run(step)
    prompt = llm.prompts[0]
    assert "- 现价：450（2026-11-13）\n- 盈亏：-10.0%\n- 占比：40.5%" in prompt
    assert "现金占比：24.3%" in prompt
    assert "- 贵州茅台 占比 40.5%，超过单个持仓上限 40%" in prompt
    for secret in ("27000", "45000", "50000", "100000", "111000"):
        assert secret not in prompt


def test_previous_actions_feed_next_run(env):
    day2 = "\n".join([
        _block("600519", "贵州茅台", "持有"),
        _block("00700", "腾讯控股", "加仓", basis="回购加码 https://example.com/buyback"),
        NVDA_HOLD,
        PORTFOLIO,
    ])
    step, llm, clock = env([DAY1, day2])
    _run(step)
    clock["today"] = date(2026, 11, 16)
    sent = _run(step)

    assert "下面是 2026-11-15 模型给出的动作，可能是错的" in llm.prompts[1]
    assert "- 600519 贵州茅台：减仓" in llm.prompts[1]
    assert "这是第一次分析" in llm.prompts[0]

    overview = sent[0]
    assert "**持有** 600519 贵州茅台｜占比 40.5% · 盈亏 -10.0%（上次：减仓）" in overview
    assert "**加仓** 00700 腾讯控股｜占比 16.2% · 盈亏 +100.0%（上次：持有）" in overview
    # 动作变了的两个都发详情，英伟达没变不发
    details = [text for text in sent[1:] if not text.startswith("**组合**")]
    assert [text.splitlines()[0] for text in details] == [
        "**600519 贵州茅台｜持有**", "**00700 腾讯控股｜加仓**",
    ]


def test_config_edit_is_picked_up_without_restart(env):
    step, _, _ = env([DAY1, DAY1])
    _run(step)
    env.config.write_text(CONFIG.replace("quantity = 20", "quantity = 40"), encoding="utf-8")
    _run(step)
    report = (env.reports / "2026-11-15.md").read_text(encoding="utf-8")
    # 英伟达 40 × 150 × 7 = 42000；总资产 45000 + 18000 + 42000 + 27000 = 132000
    assert "42,000.00" in report and "132,000.00" in report


def test_related_open_advice_goes_into_prompt(env, advice_md):
    month = env.advice / "2026-10"
    month.mkdir(parents=True)
    expiry = date(2026, 11, 20)
    (month / "2026-10-26-1.md").write_text(
        advice_md(symbol="0700.HK", expiry=expiry).replace("id: tmp", "id: 2026-10-26-1"),
        encoding="utf-8")
    (month / "2026-10-26-2.md").write_text(
        advice_md(symbol="AAPL", expiry=expiry).replace("id: tmp", "id: 2026-10-26-2"),
        encoding="utf-8")
    (env.advice / "lessons.md").write_text(
        "## 2026-11-10 · NVDA · 2026-10-26-9 · 到期结案\n不要追高。\n", encoding="utf-8")
    step, llm, _ = env([DAY1])
    _run(step)
    prompt = llm.prompts[0]
    assert "- 2026-10-26-1 | 0700.HK 测试标的" in prompt
    assert "2026-10-26-2" not in prompt
    assert "不要追高。" in prompt


def test_missing_config_does_not_call_model(env):
    step, llm, _ = env([DAY1])
    env.config.unlink()
    sent = _run(step)
    assert len(sent) == 1 and "holdings.example.toml" in sent[0]
    assert sent[0].startswith("**持仓日报 2026-11-15** 未生成")
    assert llm.prompts == []


def test_invalid_config_lists_problems(env):
    step, llm, _ = env([DAY1])
    env.config.write_text(CONFIG.replace('market = "HK"', 'market = "LSE"'), encoding="utf-8")
    sent = _run(step)
    assert len(sent) == 1 and "LSE" in sent[0]
    assert llm.prompts == []


def test_fx_failure_does_not_call_model(env):
    async def no_hkd(currencies):
        return {"CNY": 1.0, "USD": 7.0}

    async def broken(currencies):
        raise OSError("连接被重置")

    for fx, needle in ((no_hkd, "HKD"), (broken, "连接被重置")):
        step, llm, _ = env([DAY1], fx=fx)
        sent = _run(step)
        assert len(sent) == 1 and "汇率" in sent[0] and needle in sent[0]
        assert llm.prompts == []
    assert not env.reports.exists() or not list(env.reports.iterdir())


def test_quote_failure_does_not_call_model(env):
    for quotes, needle in (({}, "现价都没取到"), (OSError("连接被重置"), "取不到现价：连接被重置")):
        step, llm, _ = env([DAY1], quotes=quotes)
        sent = _run(step)
        assert len(sent) == 1 and needle in sent[0]
        assert sent[0].startswith("**持仓日报 2026-11-15** 未生成")
        assert llm.prompts == []
    assert not env.reports.exists() or not list(env.reports.iterdir())


def test_model_price_fields_are_ignored(env):
    reply = DAY1.replace("- action: 减仓", "- action: 减仓\n- price: 9999\n- price_date: 2026-11-13")
    step, _, _ = env([reply])
    sent = _run(step)
    assert "**减仓** 600519 贵州茅台｜占比 40.5% · 盈亏 -10.0%" in sent[0]
    assert "9999" not in sent[0] and "9999" not in sent[1]


def test_model_failure(env):
    step, _, _ = env([RuntimeError("Cursor run timed out")])
    sent = _run(step)
    assert len(sent) == 1
    assert "模型调用失败：Cursor run timed out" in sent[0]


def test_no_valid_advice_keeps_raw_reply(env):
    step, _, _ = env(["今天没有结论。"])
    sent = _run(step)
    assert len(sent) == 1 and "没有合法的持仓建议" in sent[0]
    assert (env.reports / "2026-11-15-raw.md").read_text(encoding="utf-8") == "今天没有结论。"
    assert not (env.reports / "2026-11-15.json").exists()
    # 没有合法动作的这次不当作「上一次的结论」
    step, llm, clock = env([DAY1], today=date(2026, 11, 16))
    _run(step)
    assert "这是第一次分析" in llm.prompts[0]


def test_partial_reply_keeps_valid_parts(env):
    reply = "\n".join([
        # 非持有、没有链接、也没有违反规则：不通过
        _block("00700", "腾讯控股", "清仓", basis="感觉要跌。"),
        # 没取到现价：建议保留，不计入估值
        _block("600519", "贵州茅台", "持有"),
        PORTFOLIO,
    ])
    step, llm, _ = env([reply], quotes={"00700": PriceQuote(180.0, DAY, "新浪行情")})
    sent = _run(step)
    overview = sent[0]
    assert "**未通过校验** 00700 腾讯控股｜占比 37.5% · 盈亏 +80.0%" in overview
    assert "**持有** 600519 贵州茅台｜现价不可用" in overview
    assert "**未覆盖** NVDA 英伟达｜现价不可用" in overview
    assert "建议未通过校验：腾讯控股（清仓需要带链接的事实依据）" in overview
    assert "没取到现价，未计入占比和盈亏：贵州茅台、英伟达。其余持仓和现金的占比因此偏高" in overview
    assert "- 现价：程序没有取到" in llm.prompts[0]
    assert "模型没有覆盖：英伟达" in overview
    # 只有腾讯有现价：16200 + 现金 27000
    assert "现金 62.5%" in overview
    assert len(sent) == 2 and sent[1].startswith("**组合**")
    saved = json.loads((env.reports / "2026-11-15.json").read_text(encoding="utf-8"))
    assert saved["actions"] == {"600519": "持有"}


def test_breach_allows_trim_without_link(env):
    reply = "\n".join([
        _block("600519", "贵州茅台", "减仓", basis="占比超过上限。"),
        TENCENT_HOLD, NVDA_HOLD, PORTFOLIO,
    ])
    step, _, _ = env([reply])
    sent = _run(step)
    assert "**减仓** 600519 贵州茅台" in sent[0]
    assert "未通过校验" not in sent[0]


def test_breach_does_not_justify_adding(env):
    reply = "\n".join([
        _block("600519", "贵州茅台", "加仓", basis="跌多了。"),
        TENCENT_HOLD, NVDA_HOLD, PORTFOLIO,
    ])
    step, _, _ = env([reply])
    sent = _run(step)
    assert "**未通过校验** 600519 贵州茅台" in sent[0]


def test_low_cash_allows_trimming_any_holding(env):
    env.config.write_text(CONFIG.replace("max_position_pct = 40", "min_cash_pct = 30"),
                          encoding="utf-8")
    reply = "\n".join([
        _block("600519", "贵州茅台", "持有"),
        _block("00700", "腾讯控股", "减仓", basis="现金低于下限，先减弹性最大的。"),
        NVDA_HOLD, PORTFOLIO,
    ])
    step, _, _ = env([reply])
    sent = _run(step)
    assert "现金占比 24.3%，低于下限 30%" in sent[0]
    assert "**减仓** 00700 腾讯控股" in sent[0]


def test_cash_only_portfolio_still_reports(env):
    env.config.write_text("[cash]\nCNY = 1000\nUSD = 100\n", encoding="utf-8")
    step, llm, _ = env([PORTFOLIO])
    sent = _run(step)
    assert "（没有持仓，只有现金）" in llm.prompts[0]
    assert "现金 100.0%" in sent[0] and "人民币 58.8%" in sent[0]
    assert len(sent) == 2 and sent[1].startswith("**组合**")


def test_hk_holding_does_not_match_a_share_advice():
    from models.holdings import Holding
    from steps.holdings_advice import _held
    hk = [Holding(symbol="00700", market="HK", name="腾讯控股", quantity=1, cost=1)]
    assert _held(hk, "0700.HK") and not _held(hk, "000700")
    a = [Holding(symbol="000700", market="SZ", name="模塑科技", quantity=1, cost=1)]
    assert _held(a, "000700") and _held(a, "000700.SZ") and not _held(a, "0700.HK")
