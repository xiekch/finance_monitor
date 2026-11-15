"""持仓分析的配置。设计见 docs/plans/2026-11-15-holdings-advice-design.md。"""
import os

from dotenv import load_dotenv

from config.investment import REPO_ROOT

load_dotenv()

# 持仓文件不进 git：仓库是公开的。示例见 holdings.example.toml。
HOLDINGS_FILE = REPO_ROOT / "config" / "holdings.toml"
HOLDINGS_EXAMPLE_FILE = REPO_ROOT / "config" / "holdings.example.toml"
# data/ 已在 .gitignore 里，报告含金额，只留在本机。
HOLDINGS_REPORT_ROOT = REPO_ROOT / "data" / "holdings"

# 持仓报告专用企微 webhook（可选，逗号分隔）；未配置时用默认 webhook
HOLDINGS_WEBHOOK_URLS: list[str] = [
    u.strip() for u in os.getenv("HOLDINGS_WEBHOOK_URL", "").split(",") if u.strip()
]

BASE_CURRENCY = "CNY"
MARKET_CURRENCY = {
    "SH": "CNY",
    "SZ": "CNY",
    "FUT": "CNY",
    "HK": "HKD",
    "US": "USD",
    "CRYPTO": "USD",
}
MARKET_LABELS = {
    "SH": "沪市",
    "SZ": "深市",
    "FUT": "国内期货",
    "HK": "港股",
    "US": "美股",
    "CRYPTO": "加密货币",
}
CASH_CURRENCIES = ("CNY", "USD", "HKD")
CURRENCY_LABELS = {"CNY": "人民币", "USD": "美元", "HKD": "港币"}

HOLD = "持有"
ACTIONS = ("加仓", HOLD, "减仓", "清仓")
ADVICE_SECTIONS = ("依据", "执行", "风险", "什么情况下改变结论")
PORTFOLIO_TITLE = "组合"

NEWS_WINDOW_DAYS = 7
# 行情里的交易日比今天早这么多天以上就不用。长假休市最长 9 天左右，再宽就可能是过期报价。
MAX_PRICE_AGE_DAYS = 10
PREVIOUS_REPORT_MAX_AGE_DAYS = 7
HOLDINGS_LESSON_LIMIT = 10

HOLDINGS_PROMPT_TEMPLATE = """今天是 {today}（北京时间）。你是一名谨慎的投资研究员，请逐个检查下面的持仓，给出今天的操作建议。

## 持仓
成本价来自我的持仓记录，现价来自行情接口，盈亏和占比由程序算好，直接使用，不要重算，也不要另找报价替换。盈亏是现价相对成本价的涨跌幅。占比是按现价算的市值占总资产（含现金）的比例。

{holdings_block}

现金占比：{cash_pct}

## 我的规则
{rules_block}

程序按上面的占比检查的结果：
{breach_block}

## 资料来源
- 现价已经在上面给出，不用再查。标着「程序没有取到」的持仓，自己查最近一个交易日的收盘价，在「依据」里写明价格、日期和来源链接。
- 搜索每个持仓最近 {news_days} 天的公告、财报、政策、行业新闻和价格走势。
- 每条事实写明日期和来源链接。查不到日期的消息不用。搜不到新信息就写「未查到新信息」，不要编造。
- 区分事实和观点。财报、公告、政策、成交数据是事实；研报评级、目标价、博主看法是观点。结论只建立在事实上，观点可以列出，但要写明是谁的观点。
- 当前仓库 advice/ 目录有历史建议、复盘和经验：advice/lessons.md 每条经验一块；advice/YYYY-MM/<id>.md 一条建议一个文件，文首是 symbol、direction 等字段，后面是正文和追加的复盘。先读 advice/lessons.md，再搜索每个持仓的历史建议。它们是模型以前的判断，可能是错的，只作参考。
- 仓库只读：不要修改、新建或提交任何文件，结果只写在回复里。

## 判断方法
- 先做往后看的判断：不看成本价和盈亏，只根据基本面、估值、催化剂和风险，判断这个标的现在值不值得按当前仓位继续持有，据此定下 action。
- 成本价和盈亏只用来安排怎么执行，比如分几批、止损位放在哪里，只能写在「执行」一节。「已经赚了很多」「已经亏了很多」「等回本再卖」都不能作为加仓、减仓或清仓的理由。
- 默认动作是持有。只有下面几种情况才改变仓位：持有理由被新事实推翻，或已经兑现完；卖出条件被触发；仓位违反我的规则；出现明确的新催化剂或新风险。
- 仓位是否违反规则以上面的程序检查结果为准，不要自己重算。
- 没有填持有理由的持仓，先在「依据」里用一句话写出你根据公开信息理解的持有逻辑，再判断它是否还成立。
- 交稿前逐条核对：每个加仓、减仓、清仓都对应一条带日期和链接的事实，或一条被违反的规则。

## 这些持仓的未到期建议
下面是模型此前对这些标的给出、还没到期的建议，可能是错的，只作参考：
{open_block}

## 上一次的结论
{prev_block}

## 最近经验
{lessons_block}

## 输出要求
- action 只能是下面四个之一：
  - 加仓：提高仓位。target_weight 写目标仓位，「执行」写在什么价位或条件下买。
  - 持有：维持当前仓位。「执行」写需要盯的价位或事件。
  - 减仓：降低仓位但不清空。target_weight 写目标仓位，「执行」写在什么价位或条件下卖。
  - 清仓：全部卖出。「执行」写在什么价位或条件下卖。
- target_weight 写占总资产的市值占比区间，只写数字，如 8-10；持有和清仓可以省略。
- summary 用一句话写核心判断，不超过 60 字。
- 每个持仓都要写一块，标题用上面给出的代码和名称，不要改写代码。
- 只输出 Markdown，不要用代码块包裹，不要写开场白和结尾。每个持仓以一级标题开头，紧接字段列表，再用二级标题写四节正文；最后一个一级标题是「组合」。一级标题只用于分隔，正文里不要再出现一级标题。格式：

# 代码 名称
- action: 持有
- target_weight: 8-10
- summary: 一句话核心判断

## 依据
...

## 执行
...

## 风险
...

## 什么情况下改变结论
...

# 组合

## 整体判断
...

## 集中度和关联风险
...

## 今天最该处理的一件事
...
"""
