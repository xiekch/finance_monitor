from datetime import date

from analyzers.portfolio import PriceQuote, apply_prices, build_portfolio
from models.holdings import parse_holdings_config
from steps.holdings_parse import (
    build_holdings_prompt,
    check_action,
    parse_holdings_response,
)

TODAY = date(2026, 11, 15)
FX = {"CNY": 1.0, "USD": 7.0, "HKD": 0.9}
DAY = date(2026, 11, 13)
# 腾讯故意不给现价。茅台 137 × 450 = 61650，英伟达 31 × 150 × 7 = 32550，现金 27000，合计 121200
QUOTES = {"600519": PriceQuote(450.0, DAY, "新浪行情"), "NVDA": PriceQuote(150.0, DAY, "新浪行情")}


def _portfolio(config, quotes=QUOTES):
    return apply_prices(build_portfolio(config, FX), quotes, config.rules)


def _config():
    return parse_holdings_config({
        "cash": {"CNY": 27000},
        "rules": {"max_position_pct": 20, "min_cash_pct": 10, "horizon": "一年以上"},
        "holdings": [
            {"symbol": "600519", "market": "SH", "name": "贵州茅台", "quantity": 137, "cost": 500,
             "thesis": "高端白酒龙头", "exit_when": "连续两个季度营收负增长"},
            {"symbol": "00700", "market": "HK", "name": "腾讯控股", "quantity": 2468, "cost": 380.5},
            {"symbol": "NVDA", "market": "US", "name": "英伟达", "quantity": 31, "cost": 120},
        ],
    })


def _prompt(**overrides):
    config = _config()
    kwargs = dict(
        today=TODAY, config=config, portfolio=_portfolio(config),
        open_summaries=[], lessons=[], previous=None,
    )
    kwargs.update(overrides)
    return build_holdings_prompt(**kwargs)


def test_prompt_has_prices_and_ratios_but_no_quantity_or_amount():
    prompt = _prompt()
    assert "### 600519 贵州茅台" in prompt and "### 00700 腾讯控股" in prompt
    assert "沪市，币种 CNY" in prompt and "港股，币种 HKD" in prompt and "美股，币种 USD" in prompt
    assert "- 成本价：500\n- 现价：450（2026-11-13）\n- 盈亏：-10.0%\n- 占比：50.9%" in prompt
    assert "- 成本价：120\n- 现价：150（2026-11-13）\n- 盈亏：+25.0%\n- 占比：26.9%" in prompt
    assert "现金占比：22.3%" in prompt
    assert "持有理由：高端白酒龙头" in prompt
    assert "卖出条件：连续两个季度营收负增长" in prompt
    assert "持有理由：（未填写）" in prompt
    # 数量和金额都不出现
    for secret in ("137", "2468", "61650", "32550", "27000", "121200"):
        assert secret not in prompt
    assert "{" not in prompt and "}" not in prompt


def test_prompt_marks_holding_without_price():
    prompt = _prompt()
    assert (
        "- 成本价：380.5\n- 现价：程序没有取到\n- 盈亏：未知\n"
        "- 占比：没有计入总资产（按买入成本算约 87.4%）"
    ) in prompt
    assert "有持仓没取到现价，没有计入总资产" in prompt


def test_prompt_tells_model_to_use_given_prices():
    prompt = _prompt()
    assert "现价已经在上面给出，不用再查" in prompt
    assert "不要重算，也不要另找报价替换" in prompt
    assert "price_url" not in prompt and "price_date" not in prompt
    assert "只能写在「执行」一节" in prompt
    assert "仓库只读" in prompt
    for action in ("加仓", "持有", "减仓", "清仓"):
        assert f"- {action}：" in prompt


def test_prompt_rules():
    prompt = _prompt()
    assert "单个持仓的市值占比不超过 20%" in prompt
    assert "现金占比不低于 10%" in prompt
    assert "投资期限：一年以上" in prompt
    assert "- 贵州茅台 占比 50.9%，超过单个持仓上限 20%" in prompt
    assert "- 英伟达 占比 26.9%，超过单个持仓上限 20%" in prompt

    config = parse_holdings_config({
        "cash": {"CNY": 90000}, "rules": {"max_position_pct": 20},
        "holdings": [{"symbol": "600519", "market": "SH", "name": "贵州茅台",
                      "quantity": 10, "cost": 500}],
    })
    prompt = _prompt(config=config, portfolio=_portfolio(config))
    assert "程序按上面的占比检查的结果：\n（没有超出规则）" in prompt

    config = parse_holdings_config({"cash": {"CNY": 1}})
    prompt = _prompt(config=config, portfolio=_portfolio(config))
    assert "（没有设定规则）" in prompt and "（没有设定占比规则）" in prompt
    assert "（没有持仓，只有现金）" in prompt
    assert "现金占比：100.0%" in prompt


def test_prompt_marks_history_as_possibly_wrong():
    prompt = _prompt(
        open_summaries=["2026-11-06-2 | 600519 贵州茅台 | 观望偏多 | 到期 2026-11-20"],
        lessons=["## 2026-11-10 · NVDA · 2026-10-26-1 · 到期结案\n没碰到目标价就不要写成已兑现。"],
        previous=(date(2026, 11, 14), {"600519": "减仓", "NVDA": "持有", "AAPL": "清仓"}),
    )
    assert "- 2026-11-06-2 | 600519 贵州茅台 | 观望偏多 | 到期 2026-11-20" in prompt
    assert "没碰到目标价就不要写成已兑现。" in prompt
    assert "下面是 2026-11-14 模型给出的动作，可能是错的" in prompt
    assert "- 600519 贵州茅台：减仓" in prompt
    assert "- NVDA 英伟达：持有" in prompt
    # 已经不在持仓里的标的、上次没有记录的标的都不列
    assert "AAPL" not in prompt and "腾讯控股：" not in prompt


def test_prompt_first_run():
    prompt = _prompt()
    assert "这是第一次分析，没有上一次的结论" in prompt
    assert "可能是错的，只作参考：\n（无）" in prompt
    assert "## 最近经验\n（无）" in prompt


RESPONSE = """好的，下面是结果。

```markdown
# 600519 贵州茅台
- action: 减仓
- price: 1,435.26
- price_date: 2026-11-13
- price_url: <https://example.com/600519>
- target_weight: 10-12
- summary: 动销走弱，反弹到 1500 上方减仓

## 依据
11 月 12 日公告下调全年目标（https://example.com/notice）。

## 执行
反弹到 1500 上方分两批卖出。

## 风险
批价继续下行。

## 什么情况下改变结论
批价连续四周回升。

# 0700.HK 腾讯控股
- **action**: 持有
- price: 387
- price_date: 2026-11-13
- price_url: https://example.com/00700

## 依据
无新变化

## 执行
盯 370 支撑。

## 风险
监管。

## 什么情况下改变结论
游戏版号收紧。

# AAPL 苹果
- action: 清仓

## 依据
不在持仓里。

# 600519 贵州茅台
- action: 清仓

## 依据
重复的一块。

# 组合

## 整体判断
白酒占比偏高。

## 集中度和关联风险
无。

## 今天最该处理的一件事
减茅台。
```
"""


def _parse(raw=RESPONSE):
    return parse_holdings_response(raw, _config().holdings)


def test_parse_fields_and_sections():
    parsed = _parse()
    assert list(parsed.advice) == ["600519", "00700"]
    maotai = parsed.advice["600519"]
    assert maotai.action == "减仓"
    assert maotai.target_weight == "10-12"
    assert maotai.summary == "动销走弱，反弹到 1500 上方减仓"
    assert maotai.sections["依据"].startswith("11 月 12 日公告")
    assert maotai.sections["什么情况下改变结论"] == "批价连续四周回升。"
    # 模型多写的 price 字段不影响解析，也不会被采用
    assert not hasattr(maotai, "price")

    tencent = parsed.advice["00700"]
    assert tencent.action == "持有"
    assert tencent.target_weight == "" and tencent.summary == ""


def test_parse_portfolio_unknown_and_missing():
    parsed = _parse()
    assert parsed.portfolio_sections["整体判断"] == "白酒占比偏高。"
    assert parsed.portfolio_sections["今天最该处理的一件事"] == "减茅台。"
    assert parsed.unknown == ["AAPL 苹果"]
    assert [h.symbol for h in parsed.missing(_config().holdings)] == ["NVDA"]


def test_parse_empty_or_garbage():
    for raw in ("", None, "模型今天不想干活"):
        parsed = _parse(raw)
        assert parsed.advice == {} and parsed.portfolio_sections == {}


def test_action_checks():
    parsed = _parse()
    maotai, tencent = parsed.advice["600519"], parsed.advice["00700"]
    assert check_action(maotai, breached=False) == ""
    assert check_action(tencent, breached=False) == ""

    maotai.sections["依据"] = "动销走弱。"
    assert "链接" in check_action(maotai, breached=False)
    # 违反规则时不要求链接
    assert check_action(maotai, breached=True) == ""

    maotai.sections["依据"] = ""
    assert "依据" in check_action(maotai, breached=True)

    tencent.action = "观望"
    assert "观望" in check_action(tencent, breached=False)
    tencent.action = ""
    assert "action" in check_action(tencent, breached=False)
