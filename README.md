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
├── app_producer_consumer.py     # 应用入口
├── config/settings.py           # API、监控标的、阈值、Redis、调度配置
├── core/
│   ├── message_queue.py         # Redis 消息队列封装
│   ├── message_types.py         # 消息类型与数据类
│   ├── smart_scheduler.py
│   ├── threshold_manager.py     # 阈值查询
│   ├── trading_hours.py         # 交易时段判断
│   ├── producers/               # 各市场各频率的生产者
│   ├── consumers/               # 存储 / 分析 / 通知 消费者
│   ├── fetchers/                # 数据抓取（yfinance / binance / 股票接口）
│   ├── analyzers/               # 波动率分析
│   └── notifiers/               # 企业微信通知
└── models/market_data.py        # PriceData / VolatilityAlert / SQLite 封装
```

## 环境要求

- Python 3.9+
- Redis（运行时由 `app_producer_consumer.py` 通过 `redis-server --daemonize yes` 自动后台启动，需要本机已安装 `redis-server`）
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
- `TASK_CONFIG`：日级、周级任务执行时间
- `PROXY` / `PROXY_URL`：海外行情抓取的本地代理（默认 `http://127.0.0.1:7897`）

## 运行

```bash
# 正常调度模式：常驻运行，按 cron 触发（默认 producer：usstock_daily + crypto）
python app_producer_consumer.py

# 启动时不立即执行一次
python app_producer_consumer.py --no-immediate

# 只执行一次后自动退出
python app_producer_consumer.py --once

# 只启动指定 producer（逗号分隔）
python app_producer_consumer.py --producers crypto,usstock_daily

# 列出所有可选 producer 后退出
python app_producer_consumer.py --list-producers
```

日志写入 `app.log` 并同时打印到控制台。

## 扩展

- **新增生产者**：继承 `core/producers/base_producer.py:BaseProducer`，实现 `produce_data()` 与 `create_trigger()`，在 `app_producer_consumer.py:setup_producers` 中注册。
- **新增消费者**：继承 `core/consumers/base_consumer.py:BaseConsumer`，声明关心的 `MessageType` 并实现 `process_message()`。
- **新增数据源**：继承 `core/fetchers/base_fetcher.py:BaseFetcher`。
