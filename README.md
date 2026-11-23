# Finance Monitor

基于 Task 管道编排的多市场行情波动监控系统。按配置的阈值实时／日级／周级监控股票、加密货币、期货等标的，触发波动时通过企业微信推送告警。

## 功能特性

- **多市场覆盖**：A 股、美股、加密货币、期货
- **多频率监控**：分钟级（1m / 5m）、日级、周级
- **管道式编排**：用 `|` 语法声明完整数据链路（Fetch → Storage → Analyze → Notify），一处定义、一目了然
- **可插拔阈值**：每个标的、每个频率独立配置波动阈值
- **数据持久化**：SQLite 存储历史行情，联合唯一索引防重
- **调度灵活**：基于 APScheduler，支持立即执行 / 仅执行一次 / 按 cron 调度
- **企业微信告警**：波动超阈值自动推送 Webhook 消息
- **AI 简报**：X / 微博推文 + 行情数据经 LLM 聚合生成 markdown 简报
- **持仓分析**：每天读本机的持仓配置，程序取现价算盈亏和占比，模型联网查消息后给出加仓 / 持有 / 减仓 / 清仓建议

## 架构

```
Task = Step | Step | Step | ...

┌──────────────────────────────────────────────────────────────┐
│ TaskRunner（共享 BackgroundScheduler）                        │
│                                                              │
│  astock_daily:                                               │
│    FetchAStock | StorageStep | VolatilityStep | NotifyStep   │
│                                                              │
│  x_briefing:                                                 │
│    FetchXPosts | StorageStep | AIBriefingStep                │
│      | Fork(StorageStep, NotifyStep)                         │
│                                                              │
│  market_briefing:                                            │
│    FetchMarketBriefing | NotifyStep                          │
│                                                              │
│  morning_briefing:                                           │
│    FetchMorningBriefing | Fork(StorageStep, NotifyStep)      │
└──────────────────────────────────────────────────────────────┘
```

Step 之间传递领域对象列表（list 进 list 出）；空列表也会交给下一步。`Fork` 将同一份数据发给多个分支分别处理。

## 目录结构

```
.
├── app.py                  # 应用入口 / CLI
├── tasks.py                # Task 注册表、复合组、build_tasks
├── config/                 # settings.py（API/DB）、schedule.py（调度）、monitor.py（标的）、social.py（X+LLM）
│   ├── holdings.py             # 持仓分析的配置和提示词
│   ├── holdings.example.toml   # 持仓配置示例
│   └── holdings.toml           # 你的持仓（gitignore，自己创建）
├── models/                 # market、social 领域模型
├── steps/                  # 管道步骤
│   ├── base.py             # Step / Chain / Fork / FetchMultiSource / Task / TaskRunner
│   ├── fetch/              # 数据获取步骤（行情 4 市场 + X / 微博 / 早报原料）
│   ├── notify/             # 推送通知步骤（终端）
│   ├── storage.py          # 透传存储步骤
│   ├── volatility.py       # 波动分析步骤
│   ├── ai_briefing.py      # AI 简报生成步骤
│   ├── morning_ai.py       # AI 早报生成步骤
│   ├── market_briefing.py  # 行情早报格式化步骤
│   ├── holdings_advice.py  # 持仓分析步骤（holdings_parse.py 负责提示词和回复解析）
│   └── publish_mp.py       # 公众号发布步骤（终端）
├── fetchers/               # 数据抓取实现（yfinance / binance / 股票接口 / trading_hours / holding_quotes 持仓现价）
├── analyzers/              # 波动率分析、threshold_manager
├── clients/                # 外部服务客户端（LLM / X / 微博 / 企微 webhook / 公众号）
├── storage/                # market_db、social_store（SQLite 持久化）
├── utils/                  # time_util 等通用工具
├── scripts/                # show_posts 等辅助脚本
├── data/                   # 运行时数据（SQLite、data/holdings/ 持仓报告，gitignore）
└── logs/                   # 运行日志（gitignore）
```

## 环境要求

- Python 3.11+（持仓配置用标准库 `tomllib` 读取）
- 依赖：`apscheduler`、`yfinance`、`requests`、`pandas`、`python-dotenv` 等

## 配置

在项目根目录创建 `.env`（已被 `.gitignore` 忽略）：

```env
# ── 行情数据 API ──
ITICK_TOKEN=your_itick_token          # A 股等（config/settings.py）
FINAGE_API_KEY=your_finage_key        # 美股等

# ── 企业微信（默认 webhook；多个 URL 用逗号分隔）──
# 用于：微博简报；波动告警、X/早报专用 webhook 未配置时的 fallback
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aaa

# ── 波动告警专用 webhook（可选，逗号分隔多个）；不填用上面的默认 webhook ──
ALERT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bbb

# ── X / 微博 AI 简报（config/social.py）──
TWITTERAPI_IO_KEY=...                 # X 数据源 twitterapi.io（x_briefing 必填）
DASHSCOPE_API_KEY=...                 # 通义千问 / DashScope（config/social.py 选 tongyi 时必填）
CURSOR_API_KEY=...                    # config/social.py 选 cursor 时必填，Cloud Agents API key
WEIBO_ACCESS_TOKEN=...                # 微博 Open API（weibo_briefing 必填）
X_BRIEFING_WEBHOOK_URL=...            # 可选，X 简报专用 webhook（逗号分隔多个）

# ── 公众号 AI 早报（config/morning_briefing.py）──
WECHAT_MP_APP_ID=...
WECHAT_MP_APP_SECRET=...
WECHAT_MP_THUMB_MEDIA_ID=...          # 草稿封面 media_id
MORNING_WEBHOOK_URL=...               # 可选，行情早报 + 晨间 AI 简报专用 webhook

# ── 持仓分析（config/holdings.py）──
HOLDINGS_WEBHOOK_URL=...              # 可选，持仓日报专用 webhook（逗号分隔多个）；不填用默认 webhook

# ── 新股上市提醒（config/new_stock.py）──
NEW_STOCK_WEBHOOK_URL=...             # 可选，新股上市专用 webhook（逗号分隔多个）；不填用默认 webhook
```

配置文件按职责拆分：

- `config/monitor.py` — `MONITOR_CONFIG`：按 `minute / daily / weekly` × `stocks / crypto / futures` 配置监控标的与阈值
- `config/schedule.py` — `TASK_SCHEDULE`：按 task key 配置 APScheduler 触发器；形如 `{"type": "cron", "kwargs": {...}}`
- `config/settings.py` — API 密钥、企微 webhook、数据库、代理等基础设施配置
- `config/social.py` — X / 微博抓取 + LLM 简报相关配置
- `config/holdings.toml` — 你的持仓、现金和仓位规则（不进 git，见下方「持仓分析」）

## 运行

### 首次准备

```bash
# 创建虚拟环境（仓库默认使用 .venv/）
python3 -m venv .venv

# 安装依赖
.venv/bin/pip install -r requirements.txt
```

下面的命令默认使用仓库内 `.venv`，无需 `source .venv/bin/activate`。
若已激活 venv 或想用系统 Python，把 `.venv/bin/python3` 换成 `python` 即可。

### 启动

```bash
# 默认：briefings 组（x_briefing → market_briefing → morning_briefing），立即串行执行 + cron 调度
.venv/bin/python3 app.py

# 完整早报链路：日 K 行情 → 三套简报，串行跑一遍后按 cron 常驻
.venv/bin/python3 app.py -t morning_pack

# 只跑一遍完整链路，不注册 cron，跑完退出
.venv/bin/python3 app.py -t morning_pack --once

# 不立即执行，仅等 cron 触发
.venv/bin/python3 app.py --no-immediate

# 多个 task 并行立即执行（默认是串行）
.venv/bin/python3 app.py -t usstock_minute,crypto_minute --parallel

# 指定企微 webhook（可多次指定，覆盖 .env）
.venv/bin/python3 app.py --webhook "https://...?key=aaa"

# 列出所有 task 与复合组
.venv/bin/python3 app.py --list-tasks
```

### 运行示例

**行情监控**

```bash
# 分钟级监控（A 股 + 加密货币）
.venv/bin/python3 app.py -t astock_minute,crypto_minute

# 日 K 更新
.venv/bin/python3 app.py -t usstock_daily,crypto_daily,astock_daily,futures_daily --once
```

**简报 / 早报**

```bash
# X 推文 AI 简报（拉取 → LLM → 企微）
.venv/bin/python3 app.py -t x_briefing --once

# 三套简报：X 简报 → 行情早报 → 公众号早报
.venv/bin/python3 app.py -t briefings --once

# 完整链路：先更新日 K，再三套简报（推荐手动触发早报时用）
.venv/bin/python3 app.py -t morning_pack --once

# 单独跑公众号早报（先拉 X 推文落库，再合成早报）
.venv/bin/python3 app.py -t morning_briefing --once
```

**复合组说明**

| 组名 | 展开为 |
|------|--------|
| `briefings` | x_briefing → market_briefing → morning_briefing |
| `morning_pack` | 四个 `*_daily` + briefings 全套 |

日志写入 `logs/app.log` 并同时打印到控制台。

## X 推文 AI 简报

按 cron 从白名单账号拉取推文 → LLM 聚合成 markdown 简报 → 企微推送。调度见 `config/schedule.py`，抓取与 LLM 参数见 `config/social.py`。简报内容仅来自本次 API 拉取；原始推文与简报均落 SQLite（供早报等其它 task 读取）。

所需环境变量：`TWITTERAPI_IO_KEY`，以及当前 LLM 后端对应的密钥（`config/social.py` 里 `_LLM_PROVIDER=tongyi` 用 `DASHSCOPE_API_KEY`，`cursor` 用 `CURSOR_API_KEY`）；可选 `X_BRIEFING_WEBHOOK_URL`（见上方配置表）。

### 配置位置 `config/social.py`

主要字段：

- `whitelist`：关注的 X 账号列表（不带 `@`）
- `window_hours`：回看窗口（小时）；search 模式下同时用于 API 时间过滤与 LLM prompt
- `social_provider.fetch_mode`：`"search"`（合并 query）或 `"timeline"`（逐账号增量）
- `social_provider.search_limit`：search 模式拉取上限
- `prompt_template`：LLM prompt，可调
- `social_provider` / `llm_provider`：数据源与模型配置
- `push_max_chars`：企微推送字符上限

### 数据落地（共用 `data/market_data.db`）

- `social_posts` 表：抓到的推文，`(platform, post_id)` 联合主键幂等去重；`created_at` / `fetched_at` 均为 UTC ISO8601
- `briefings` 表：每次简报，含 markdown / sections / token 用量；`degraded=1` 表示 LLM 失败时的降级简报

### 失败行为

- API 失败或拉到 0 条：不发简报，下次 cron 重试
- LLM 失败：发一条降级简报到企微（说明哪几个账号收到多少条 + 错误信息）+ `briefings` 表记 `degraded=1`
- 推送失败：仅记 error log；简报已落库，可查询 `briefings` 表手工补推

## 公众号 AI 早报

`morning_briefing` task：先拉取 X 推文落库，再读社交帖 + 监控标的行情 → LLM 合成 → 企微推送 + 微信公众号发布。配置见 `config/social.py` 与 `config/morning_briefing.py`。运行命令见上方「运行示例」。

所需环境变量：`TWITTERAPI_IO_KEY`、当前 LLM 后端对应的密钥（`tongyi` 用 `DASHSCOPE_API_KEY`，`cursor` 用 `CURSOR_API_KEY`）、`WECHAT_MP_APP_ID`、`WECHAT_MP_APP_SECRET`、`WECHAT_MP_THUMB_MEDIA_ID`；可选 `MORNING_WEBHOOK_URL`（见上方配置表）。

## 持仓分析

`holdings_advice` task：每天 08:40 读 `config/holdings.toml`，程序取现价并算好盈亏和占比，模型联网查每个持仓最近 7 天的消息，给出加仓 / 持有 / 减仓 / 清仓建议，推送到企微。它不在任何复合组里，要单独指定。

```bash
# 第一次用：复制示例，填上自己的持仓
cp config/holdings.example.toml config/holdings.toml

# 跑一次看结果（单次约 5～7 分钟）
.venv/bin/python3 app.py -t holdings_advice --once

# 常驻，每天 08:40 运行
.venv/bin/python3 app.py -t holdings_advice --no-immediate
```

所需环境变量：`CURSOR_API_KEY`（`config/social.py` 的 `llm_provider` 要选 `cursor`，只有它能联网搜索）；可选 `HOLDINGS_WEBHOOK_URL`。

### 改持仓

直接改 `config/holdings.toml`。每次运行都会重新读这个文件，常驻进程不用重启。字段说明写在 `config/holdings.example.toml` 的注释里。配置写错时不会调用模型，企微会收到一条列出全部问题的消息。

支持的市场：`SH` / `SZ`（A 股和场内 ETF）、`HK`（港股）、`US`（美股和美股 ETF）、`CRYPTO`（加密货币）、`FUT`（国内期货，也可以用来记实物金），以及 `CNY` / `USD` / `HKD` 现金。

### 数据怎么流动

1. 程序取现价和汇率：A 股、港股、美股、国内期货的现价和美元、港币汇率来自新浪行情，加密货币来自币安。
2. 程序算出每个持仓的盈亏比例、市值占比和现金占比，检查仓位规则。
3. 把成本价、现价、盈亏比例、占比、规则检查结果、持有理由和卖出条件发给模型。**持仓数量和金额不发**。
4. 模型联网查消息，对每个持仓给出动作和依据。
5. 程序校验每条建议：加仓、减仓、清仓必须有带链接的事实依据；减仓和清仓也可以对应一条被违反的规则。
6. 完整报告存到 `data/holdings/YYYY-MM-DD.md`，再推送企微。

### 哪些内容会离开本机

本仓库是公开的，所以：

- `config/holdings.toml` 和 `data/holdings/` 都在 `.gitignore` 里，不会被提交。持仓报告不写进 `advice/`。
- 发给模型的只有价格（成本价、现价）和比例（盈亏、占比）。
- 企微推送只有比例（占比、盈亏百分比）和现价；模型写的「执行」一节可能提到成本价。
- 数量、市值、盈亏金额只出现在本机的 `data/holdings/` 报告里。

### 推送内容

- 一条总览：总盈亏比例、现金占比、币种分布，每个持仓一行（动作、占比、盈亏、一句话判断），以及超出规则、现价不可用、建议未通过校验的提醒。
- 动作不是「持有」，或动作和上一次不同的持仓，各发一条详情（依据、执行、风险、什么情况下改变结论）。
- 一条组合层面的判断。

### 要知道的限制

- 盈亏 = 市值 − 成本 + 分红。分红由程序自动拉取（A 股个股东方财富、沪深 ETF 新浪、港股美股雅虎财经），把 `since`（持有起始日，见 `holdings.example.toml`）之后除息的税前现金分红 × 现在的数量折成人民币记进去；没写 `since` 的持仓不算分红，报告里会提醒。分红接口取不到的持仓，推送会注明「盈亏未含分红」。
- 分红按税前算，不含红利税；不含送转股，也不含已实现盈亏。除息日当天就计入，不等钱到账。持仓数量中途变过的，分红按现在的数量算，会有偏差。和券商 App 里的浮动盈亏金额可能仍对不上（券商常把分红摊薄进成本价）。
- 行情里的交易日比今天早 10 天以上的报价不用。没取到现价的持仓不计入总资产，这时其余持仓的占比会偏高，推送里会注明。所有持仓都没取到现价时不调用模型。
- 加密货币按币安的 USDT 交易对取价，当作美元。
- 不支持场外基金。

## 新股上市提醒

`new_stock_listing` task：每天 09:00 从 akshare（东方财富新股表，覆盖沪深北）查「上市日期」是今天的新股，有就推送一条企微 markdown（名称、代码、板块、发行价、发行市盈率、发行量、申购日），没有就不发。不需要额外密钥。推送用 `NEW_STOCK_WEBHOOK_URL`（可选，逗号分隔多个），没配就用默认 `WECOM_WEBHOOK_URL`。它不在任何复合组里，要单独指定。

```bash
# 立即查一次今天有没有新股上市
.venv/bin/python3 app.py -t new_stock_listing --once

# 常驻，每天 09:00 运行
.venv/bin/python3 app.py -t new_stock_listing --no-immediate
```

接口连续失败 3 次后任务报错并写入 `logs/app.log`，不会推送。

## 扩展

- **新增数据链路**：
  1. 在 `steps/` 下实现新的 Step（继承 `Step`，实现 `async process(items)`，list 进 list 出）
  2. 在 `tasks.py` 的 `TASK_REGISTRY` 中用 `|` 语法组合成 Task 并注册
  3. 在 `config/schedule.py:TASK_SCHEDULE` 加该 task key 的触发器配置
- **新增数据源**：继承 `fetchers/base_fetcher.py:BaseFetcher`
