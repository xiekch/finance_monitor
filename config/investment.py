"""投资建议与复盘的配置。设计见 docs/plans/2026-10-26-investment-advice-design.md。"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADVICE_ROOT = REPO_ROOT / "advice"
ADVICE_REPO_URL = "https://github.com/xiekch/finance_monitor"
ADVICE_REPO_REF = "main"
MAX_ADVICE = 3
LESSON_LIMIT = 30
MAX_HORIZON_DAYS = 31
MAX_REFERENCE_AGE_DAYS = 3
MAX_REVIEWS_PER_RUN = 20
# 建议要搜索并读仓库，单次实测 7 分钟，比简报的 900 秒留更多余量
INVESTMENT_TIMEOUT_SEC = 1500
DISCLAIMER = "模型生成，非投资建议"

ADVICE_PROMPT_TEMPLATE = """今天是 {today}（北京时间）。你是一名谨慎的投资研究员，请给出 1～{max_advice} 条可以事后对照验证的投资建议。标的主要从 A 股（个股和场内 ETF）和海外 ETF 里选，也可以直接看黄金；行业板块、债券用对应的 ETF 表达。

## 资料来源
- 自己联网搜索最新行情、新闻、公告和研报，不使用已抓取的行情、调用方提供的行情表或社媒帖子。
- 当前仓库的 advice/ 目录沉淀了历史建议、复盘结果和经验：
  - advice/lessons.md：每条经验一块，标题是「## 日期 · 标的 · 建议 id · 复盘种类」
  - advice/YYYY-MM/<id>.md：一条建议一个文件。文首是 symbol、direction、reference_price、target_price、stop_price、status 等字段；正文是理由、目标价、失效条件、参考价、观察条件五节；之后追加的「## 复盘 …」是到期结案、周回溯、月回溯的结果
- 动笔前先读 advice/lessons.md 全文，不只看下面的最近经验；对每个准备给建议的标的，先在 advice/ 里搜索它的历史建议和复盘，避免重复犯错。
- 仓库只读：不要修改、新建或提交任何文件，结果只写在回复里。

## 未到期建议
下面这些标的已有未到期建议，不要再发新建议：
{open_block}

## 最近经验
{lessons_block}

## 输出要求
- symbol 写法：A 股个股和 ETF 写 6 位数字代码（如 601857、512480），美股上市的 ETF 写 ticker（如 SOXX、GLD、TLT），其他海外市场的 ETF 写代码加交易所后缀（如港股 3033.HK），黄金写现货代码 XAUUSD（currency 写 USD，价格按美元/盎司）。
- 行业板块、债券用 ETF 时，name 写「板块或品类（ETF 名）」，如「半导体（半导体ETF）」「美国长债（iShares 20+ Year Treasury）」；价格写 ETF 的成交价，债券不写收益率，看多债券 ETF 即看收益率下行。
- direction 只能是看多、看空、观望偏多、观望偏空。不要写不带方向的「观望」。advice/ 里旧文件的裸「观望」是历史值，新建议不要照抄。
  - 看多：target_price 高于 reference_price；若有 stop_price，必须低于 reference_price。
  - 看空：target_price 低于 reference_price；若有 stop_price，必须高于 reference_price。
  - 观望偏多：现在不追，等价格回落到 target_price 再评估做多或承接。target_price 低于 reference_price；若有 stop_price，必须高于 reference_price（价格先涨破失效位，这条等待作废）。
  - 观望偏空：现在不追空，等价格反弹或站上 target_price 再评估做空或减仓。target_price 高于 reference_price；若有 stop_price，必须低于 reference_price（价格先跌破失效位，这条等待作废；跌破之后要不要做空另开建议）。
- 参考价为 100 时：看多可以写 target 120、stop 90；看空可以写 target 80、stop 110；观望偏多可以写 target 90、stop 110；观望偏空可以写 target 110、stop 90。
- stop_price 可选：失效条件里有明确价位时填写，并遵守上面的相对位置；没有明确价位就省略。
- reference_price 必须是真实成交价，reference_date 在 {earliest_reference} 至 {today} 之间，reference_url 是能打开的来源链接。
- expiry_date 是具体日期，不晚于 {latest_expiry}。
- 价格字段只写数字，不带单位和千分位；币种写在 currency。
- summary 用一句话写核心判断和触发条件，不超过 60 字，不写开头的价格复述，如「AI 资本开支未降温，财报前回调到 140 以下可分批看多」。
- 正文五节写给人看：理由写清催化剂和依据，失效条件写清什么情况下这条建议作废。
- 只输出 Markdown，不要用代码块包裹，不要写开场白和结尾。每条建议以一级标题「# 建议 N」开头，紧接字段列表，再用二级标题写五节正文。一级标题只用于分隔建议，正文里不要再出现一级标题。下面用看多演示字段格式；观望类把 direction 写成观望偏多或观望偏空，价格按上面的相对位置填。格式：

# 建议 1
- symbol: 代码
- name: 名称
- direction: 看多
- summary: 一句话核心判断
- expiry_date: YYYY-MM-DD
- currency: USD
- reference_price: 数字
- reference_date: YYYY-MM-DD
- reference_url: https://...
- target_price: 数字
- stop_price: 数字

## 理由
...

## 目标价
...

## 失效条件
...

## 参考价
...

## 观察条件
...

# 建议 2
...
"""

REVIEW_PROMPT_TEMPLATE = """今天是 {today}（北京时间）。请对下面这条投资建议做「{kind_label}」复盘。

## 要求
- 自己联网搜索价格和事件，不使用调用方提供的行情。
- 价格评估窗口是 {window_start} 至 {window_end}。判断建议对错、是否碰到目标价或失效条件，只看这个窗口；窗口之后的走势最多在事件过程里提一句，不用来判断对错，也不据此写经验。
- 观望类建议：先写清当初等的是哪一侧，再写这次等待是否值得。观望偏多是等价格回落到 target_price（低于参考价）再评估做多或承接；观望偏空是等价格反弹或站上 target_price（高于参考价）再评估做空或减仓。历史文件若 direction 仍是不带方向的「观望」，按 target_price 相对 reference_price 归侧：低于参考价视为偏多（等回撤），高于参考价视为偏空（等站上），复盘里点明这一侧，不要只写「观望」。价格行写窗口内是否触及 target_price，触及时写日期和之后的走势；有 stop_price 时也写是否触及。窗口内的涨跌本身不是方向对错的唯一标准。
- 可以只读参考当前仓库 advice/ 里同一标的的其他建议和 advice/lessons.md；不要修改、新建或提交任何文件。
- 下面的建议全文已包含之前的复盘，不要把已经写过的事实再当成新发现。
{kind_rule}

## 输出格式
只输出下面这一节，不要写其他内容：

## 复盘 {today} {kind_label}
- 价格：参考价、目标价、复盘时价格（注明日期和来源链接），窗口内有没有碰到目标价或失效条件
- 逻辑：当初的理由和催化剂是否兑现
- 事件过程：窗口内按时间发生了什么
- 经验：一句可复用的话；没有就写「无」

## 建议全文
{doc}
"""

REVIEW_KIND_RULES = {
    "due": "- 这是到期结案，必须输出上面的复盘节，不能返回 NO_NEW_FINDING。",
    "weekly": (
        "- 只有出现新发现才输出复盘节。新发现指建议正文和已有复盘都没写过的事实：价格路径改变了结论、"
        "催化剂兑现或落空、失效条件被触发、目标价被碰到，或出现相反证据。没有新发现时只输出 NO_NEW_FINDING 这一个词。"
    ),
}
REVIEW_KIND_RULES["monthly"] = REVIEW_KIND_RULES["weekly"]
