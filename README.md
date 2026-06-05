# Finance Monitor

基于生产者-消费者模式的多市场行情波动监控系统。按配置的阈值实时／日级／周级监控股票、加密货币、期货等标的，触发波动时通过企业微信推送告警。

## 功能特性

- **多市场覆盖**：A 股、美股、加密货币、期货
- **多频率监控**：分钟级（1m / 5m）、日级、周级
- **生产者-消费者解耦**：Producer 抓数据 → Redis Pub/Sub → 多个 Consumer 并行处理
- **可插拔阈值**：每个标的、每个频率独立配置波动阈值
- **数据持久化**：SQLite 存储历史行情，联合唯一索引防重
- **调度灵活**：基于 APScheduler，支持立即执行 / 仅执行一次 / 按 cron 调度
- **企业微信告警**：波动超阈值自动推送 Webhook 消息

## 架构

```
┌─────────────┐    publish     ┌──────────┐   subscribe   ┌──────────────────────┐
│  Producers  │ ─────────────► │  Redis   │ ────────────► │  Consumers           │
│             │                │  Pub/Sub │               │                      │
│ - AStock    │                └──────────┘               │ - StorageConsumer    │
│ - USStock   │                                           │ - VolatilityConsumer │
│   (min/d/w) │                                           │ - NotificationConsumer│
│ - Crypto    │                                           │     │                │
└─────────────┘                                           │     ▼                │
                                                          │  WeCom Webhook       │
                                                          └──────────────────────┘
```

- 消息类型：`PRICE_DATA` / `HISTORICAL_PRICE_DATA` / `VOLATILITY_ALERT` / `SYSTEM_EVENT`
- 每个 Consumer 为其关心的每种消息类型起一个独立订阅线程

## 目录结构

```
.
├── app.py                  # 应用入口 / PRODUCER_REGISTRY / trigger 注入
├── config/                 # settings.py（监控/调度）、social.py（X+LLM）
├── models/                 # messages、market、social 数据类
├── infra/                  # message_queue（Redis pub/sub）、trading_hours
├── clients/                # llm_client、social_client（外部 API 封装）
├── storage/                # market_db、social_store（SQLite 持久化）
├── producers/              # 各市场各频率的生产者
├── consumers/              # 存储 / 分析 / 通知 / AI 简报 消费者
├── fetchers/               # 数据抓取（yfinance / binance / 股票接口）
├── analyzers/              # 波动率分析、threshold_manager
└── notifiers/              # 企业微信通知
```

## 环境要求

- Python 3.9+
- Redis（**可选**）：默认消息总线是进程内 in-memory backend，无需 Redis。如需切回 Redis，把 `config/settings.py` 里的 `MQ_BACKEND` 改成 `'redis'`，`app.py` 会通过 `redis-server --daemonize yes` 启动本机 Redis（此时需要本机已安装 `redis-server`）
- 依赖：`redis`、`apscheduler`、`yfinance`、`requests`、`pandas`、`python-dotenv` 等

## 配置

在项目根目录创建 `.env`（已被 `.gitignore` 忽略）：

```env
ITICK_TOKEN=your_itick_token
FINAGE_API_KEY=your_finage_key
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
```

监控标的、阈值、调度时间在 `config/settings.py` 中调整：

- `MONITOR_CONFIG`：按 `minute / daily / weekly` × `stocks / crypto / futures` 配置
- `PRODUCER_SCHEDULE`：按 producer key 配置 APScheduler 触发器；形如 `{"type": "cron", "kwargs": {...}}`，`None` 表示无调度。运行频次与 producer 类解耦，改时间不用动代码。
- `PROXY` / `PROXY_URL`：海外行情抓取的本地代理（默认 `http://127.0.0.1:7897`）
- `MQ_BACKEND`：消息总线 backend，`'memory'`（默认，进程内）或 `'redis'`（跨进程）

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
# 正常调度模式：常驻运行，按 cron 触发（默认 producer：usstock_daily + crypto_daily）
.venv/bin/python3 app.py

# 启动时不立即执行一次
.venv/bin/python3 app.py --no-immediate

# 只执行一次后自动退出
.venv/bin/python3 app.py --once

# 只启动指定 producer（逗号分隔）
.venv/bin/python3 app.py --producers usstock_minute,crypto_minute

# 指定企微推送 webhook（覆盖 .env 中的 WECOM_WEBHOOK_URL）
.venv/bin/python3 app.py --webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"

# 列出所有可选 producer 后退出
.venv/bin/python3 app.py --list-producers
```

日志写入 `app.log` 并同时打印到控制台。

## X 推文 AI 简报

并行链路：每天按 cron 从配置的 X 账号白名单拉取增量推文 → 调 LLM 聚合成 markdown 简报 → 通过现有企微 webhook 推送；原始推文与简报均落 SQLite。

### 启动

```bash
# 单独跑（每天按 SOCIAL_CONFIG["cron_hours"] 触发）
python app.py --producers x_briefing

# 与行情 producer 一起跑
python app.py --producers crypto_daily,usstock_daily,x_briefing

# 立即跑一次（联调用；since_id 已更新后再跑会拉到 0 条 → 不重复推送）
python app.py --producers x_briefing --once
```

### 环境变量（追加到 `.env`）

```env
DASHSCOPE_API_KEY=...            # 阿里百炼 / 通义千问 API key
TWITTERAPI_IO_KEY=...            # twitterapi.io 的 key（默认 X 数据源；
                                 # 如改用 socialdata.tools 则配 SOCIALDATA_API_KEY）
```

### 配置位置 `config/social.py`

主要字段：

- `enabled`：总开关。`False` 时 `XBriefingProducer` / `AIBriefingConsumer` 都不实例化
- `whitelist`：关注的 X 账号列表（不带 `@`）
- `cron_hours`：简报时段，例 `"8,20"` 表示每天 8 点和 20 点各一次
- `window_hours`：每次简报覆盖的回看窗口（仅作为 LLM prompt 上下文，不影响 since_id 增量）
- `prompt_template` / `user_prompt_extra`：LLM prompt，可调
- `social_provider`：第三方 X 聚合服务，默认 `twitterapi_io`；可切 `socialdata`，client 在 [clients/social_client.py](clients/social_client.py) 按 `name` 派发
- `llm_provider`：LLM，默认 `tongyi`（DashScope via OpenAI 兼容协议 + `langchain_openai.ChatOpenAI`），`model` 默认 `qwen3.6-plus`，`max_tokens` 8192（qwen3 thinking 模型需要预留 thinking token 配额）
- `push_max_chars`：推送给企微的字符上限（4096 字节内安全冗余）

### 数据落地（共用 `market_data.db`）

- `social_posts` 表：抓到的推文，`post_id` 为主键自动幂等去重
- `briefings` 表：每次简报，含 markdown / sections / token 用量；`degraded=1` 表示 LLM 失败时的降级简报

### 失败行为

- 单账号抓取失败：跳过该账号，记 warning，其他账号继续
- 全部账号失败 / 拉到 0 条：不发简报消息，下次 cron 重试
- LLM 失败：发一条降级简报到企微（说明哪几个账号收到多少条 + 错误信息）+ `briefings` 表记 `degraded=1`
- 推送失败：仅记 error log；简报已落库，可查询 `briefings` 表手工补推

## 扩展

- **新增生产者**：
  1. 继承 `producers/base_producer.py:BaseProducer`，只需实现 `produce_data()`；触发器由外部注入，不要在类里写 cron。
  2. 在 `app.py:PRODUCER_REGISTRY` 加一条 `"key": (YourProducer, {extra_kwargs})`。
  3. 在 `config/settings.py:PRODUCER_SCHEDULE` 加该 key 的触发器配置（或 `None` 表示无调度）。
- **新增消费者**：继承 `consumers/base_consumer.py:BaseConsumer`，声明关心的 `MessageType` 并实现 `process_message()`。
- **新增数据源**：继承 `fetchers/base_fetcher.py:BaseFetcher`。
