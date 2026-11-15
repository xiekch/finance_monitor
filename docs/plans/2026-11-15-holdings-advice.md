# Holdings Advice Implementation Plan

> 实施后的改动：现价改由程序取（`fetchers/holding_quotes.py`，新浪行情和币安），连同盈亏比例和占比写进提示词，模型不再回传现价。下面的 Goal、Architecture 和各 Task 是最初的计划，保留作记录；现行做法以 `2026-11-15-holdings-advice-design.md` 为准。

**Goal:** 新增 `holdings_advice` 任务：每天读取 `config/holdings.toml`，让模型联网搜索现价和新闻，逐个持仓给出加仓、持有、减仓或清仓的建议，程序计算市值、盈亏和占比后推送企微。

**Architecture:** 不接现有行情抓取。程序先按买入成本算成本占比并取汇率，模型在回复里给出每个持仓的现价（带日期和链接）和建议，程序校验后估值、检查规则、落盘到 `data/holdings/`、推送。设计见 `docs/plans/2026-11-15-holdings-advice-design.md`。

**Tech Stack:** Python 3.11+（`tomllib`）、现有 APScheduler 任务注册、Cursor cloud agent、`WeChatNotifier`、pytest。不新增依赖。

本计划在同一会话里直接执行，所以只列任务、文件和测试点，不重复贴完整代码。每个任务先写失败的测试，再实现，再跑 `.venv/bin/python3 -m pytest -q`。

---

### Task 1: 配置模型和校验

- Create: `config/holdings.py`、`config/holdings.example.toml`、`models/holdings.py`
- Modify: `.gitignore`（加 `config/holdings.toml`）
- Test: `tests/test_holdings_config.py`
- 测试点：合法配置解析；币种随 market；一次报出全部问题；symbol 重复、未知字段、未知市场、symbol 不是字符串、现金币种不认识；`symbol_key` 把 `0700.HK`、`00700`、`SH600519` 归一。

### Task 2: 读配置、读写报告

- Create: `storage/holdings_store.py`
- Test: `tests/test_holdings_config.py`（`load_holdings_config`）、`tests/test_holdings_store.py`
- 测试点：文件不存在时提示复制示例；TOML 语法错误；修改文件后再读得到新内容；报告和动作落盘；`latest_actions` 只取 7 天内最近一份，坏文件跳过。

### Task 3: 成本占比和估值

- Create: `analyzers/portfolio.py`
- Test: `tests/test_portfolio_valuation.py`
- 测试点：多币种成本占比；带现价后的市值、盈亏、市值占比、币种分布；没有现价的持仓不计入；合约乘数；超出单票上限、低于现金下限。

### Task 4: 汇率

- Modify: `fetchers/sina_quote.py`
- Test: `tests/test_sina_quote.py`
- 测试点：从 `fx_susdcny` 字段取最新价；日期过旧或缺失返回 None；人民币恒为 1。

### Task 5: 提示词和回复解析

- Create: `steps/holdings_parse.py`
- Modify: `storage/advice_store.py`（`open_summaries_for`）
- Test: `tests/test_holdings_parse.py`
- 测试点：提示词有成本价和成本占比、没有数量和金额；上一次结论和未到期建议带「可能是错的」；首次运行的说法；解析字段、四节正文、组合块、代码围栏、未知标题、重复块；现价校验；动作校验。

### Task 6: 编排、报告、推送

- Create: `steps/holdings_advice.py`
- Modify: `steps/notify/investment.py`、`steps/notify/__init__.py`
- Test: `tests/test_holdings_step.py`
- 测试点：完整一轮的落盘和推送条数；推送无金额、报告有金额；非持有和动作变化才发详情；配置缺失、汇率失败、模型失败、没有合法建议；同一个 step 对象读到修改后的配置；上次动作进入提示词和总览。

### Task 7: 注册任务和文档

- Modify: `tasks.py`、`config/schedule.py`、`README.md`
- Test: `tests/test_holdings_tasks.py`
- 测试点：`holdings_advice` 在注册表里、cron 为 08:40、不在任何复合组里。

### Task 8: 实测

- 用临时持仓文件和假模型跑一遍 `HoldingsAdviceStep`，汇率走真实新浪接口，确认报告和推送正文。
- 真实模型调用约 7 分钟并消耗额度，由使用者决定何时运行：`.venv/bin/python3 app.py -t holdings_advice --once`。
