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

每个 Step 的输出是下一个 Step 的输入；返回 `None` 则链路终止。`Fork` 将同一份数据发给多个分支并行处理。

## 目录结构

```
.
├── app.py                  # 应用入口 / Task 注册表 / CLI
├── config/                 # settings.py（API/DB）、schedule.py（调度）、monitor.py（标的）、social.py（X+LLM）
├── models/                 # messages、market、social 数据类
├── steps/                  # 管道步骤
│   ├── base.py             # Step / Chain / Fork / FetchMultiSource / Task / TaskRunner
│   ├── fetch_*.py          # 数据获取步骤（8 个）
│   ├── storage.py          # 透传存储步骤
│   ├── volatility.py       # 波动分析步骤
│   ├── ai_briefing.py      # AI 简报生成步骤
│   └── notify.py           # 推送通知步骤（终端）
├── infra/                  # trading_hours
├── clients/                # llm_client、social_client（外部 API 封装）
├── storage/                # market_db、social_store（SQLite 持久化）
├── utils/                  # time_util 等通用工具
├── fetchers/               # 数据抓取（yfinance / binance / 股票接口）
├── analyzers/              # 波动率分析、threshold_manager
└── notifiers/              # 企业微信通知
```

## 环境要求

- Python 3.9+
- 依赖：`apscheduler`、`yfinance`、`requests`、`pandas`、`python-dotenv` 等

## 配置

在项目根目录创建 `.env`（已被 `.gitignore` 忽略）：

```env
ITICK_TOKEN=your_itick_token
FINAGE_API_KEY=your_finage_key
# 多个 webhook 用逗号分隔
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aaa,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bbb

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
```

配置文件按职责拆分：

- `config/monitor.py` — `MONITOR_CONFIG`：按 `minute / daily / weekly` × `stocks / crypto / futures` 配置监控标的与阈值
- `config/schedule.py` — `TASK_SCHEDULE`：按 task key 配置 APScheduler 触发器；形如 `{"type": "cron", "kwargs": {...}}`
- `config/settings.py` — API 密钥、企微 webhook、数据库、代理等基础设施配置
- `config/social.py` — X / 微博抓取 + LLM 简报相关配置

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
# 正常调度模式：常驻运行，按 cron 触发（默认 task：usstock_daily + crypto_daily + x_briefing + market_briefing + morning_briefing）
.venv/bin/python3 app.py

# 启动时不立即执行一次
.venv/bin/python3 app.py --no-immediate

# 只执行一次后保持运行等待处理完成
.venv/bin/python3 app.py --once

# 只启动指定 task（逗号分隔）
.venv/bin/python3 app.py -t usstock_minute,crypto_minute

# 指定企微推送 webhook（可多次指定，覆盖 .env 中的 WECOM_WEBHOOK_URL）
.venv/bin/python3 app.py --webhook "https://...?key=aaa" --webhook "https://...?key=bbb"

# 列出所有可选 task 后退出
.venv/bin/python3 app.py --list-tasks
```

日志写入 `app.log` 并同时打印到控制台。

## X 推文 AI 简报

按 cron 从白名单账号拉取推文 → LLM 聚合成 markdown 简报 → 企微推送。调度见 `config/schedule.py`，抓取与 LLM 参数见 `config/social.py`。简报内容仅来自本次 API 拉取；原始推文与简报均落 SQLite（供早报等其它 task 读取）。

### 启动

```bash
# 单独跑
python app.py -t x_briefing

# X 简报 + 微博简报（独立 task）
python app.py -t x_briefing,weibo_briefing

# 与行情 task 一起跑
python app.py -t crypto_daily,usstock_daily,x_briefing

# 立即跑一次
python app.py -t x_briefing --once
```

### 环境变量（追加到 `.env`）

```env
DASHSCOPE_API_KEY=...            # 阿里百炼 / 通义千问 API key
TWITTERAPI_IO_KEY=...            # twitterapi.io 的 key（默认 X 数据源；
                                 # 如改用 socialdata.tools 则配 SOCIALDATA_API_KEY）
```

### 配置位置 `config/social.py`

主要字段：

- `whitelist`：关注的 X 账号列表（不带 `@`）
- `window_hours`：回看窗口（小时）；search 模式下同时用于 API 时间过滤与 LLM prompt
- `social_provider.fetch_mode`：`"search"`（合并 query）或 `"timeline"`（逐账号增量）
- `social_provider.search_limit`：search 模式拉取上限
- `prompt_template`：LLM prompt，可调
- `social_provider` / `llm_provider`：数据源与模型配置
- `push_max_chars`：企微推送字符上限

### 数据落地（共用 `market_data.db`）

- `social_posts` 表：抓到的推文，`(platform, post_id)` 联合主键幂等去重；`created_at` / `fetched_at` 均为 UTC ISO8601
- `briefings` 表：每次简报，含 markdown / sections / token 用量；`degraded=1` 表示 LLM 失败时的降级简报

### 失败行为

- API 失败或拉到 0 条：不发简报，下次 cron 重试
- LLM 失败：发一条降级简报到企微（说明哪几个账号收到多少条 + 错误信息）+ `briefings` 表记 `degraded=1`
- 推送失败：仅记 error log；简报已落库，可查询 `briefings` 表手工补推

## 扩展

- **新增数据链路**：
  1. 在 `steps/` 下实现新的 Step（继承 `Step`，实现 `async process(data)`）
  2. 在 `app.py` 中用 `|` 语法组合成 Task 并注册
  3. 在 `config/schedule.py:TASK_SCHEDULE` 加该 task key 的触发器配置
- **新增数据源**：继承 `fetchers/base_fetcher.py:BaseFetcher`
