# 生产者消费者 → Task 编排 — 代码分析

日期：2026-06-07

## 1. 需求概述

重构现有的 Producer-Consumer pub/sub 模式为 Task 编排模式：
- 去掉 producer/consumer 的角色区分，统一为 **Task**（一条完整的数据处理链）
- 每个 Task 由多个 **Step** 串联，上一步输出作为下一步输入
- 在一个地方声明完整链路，消除 consumer 内部隐式 `mq.publish` 串联
- 启动系统 = 启动一组 Task，而不是分别启动 producer 和 consumer

需求类型：**修改业务逻辑**（核心架构模式变更）

## 2. 现有数据流全景

### 2.1 Chain 1 — 价格监控

```
AStockProducer ─┐
USStockProducer ─┤── produce_data() → [PRICE_DATA] ──→ StorageConsumer.save (存 DB)
CryptoProducer  ─┤                                  └→ VolatilityConsumer.analyze
FuturesProducer ─┘                                       │
                                                         ↓ mq.publish(VOLATILITY_ALERT)
                                                     NotificationConsumer.push (推送企微)
```

- Producer 还会发 `HISTORICAL_PRICE_DATA`，仅 StorageConsumer 消费

### 2.2 Chain 2 — 社交简报

```
XBriefingProducer ───┐
WeiboBriefingProducer┘── produce_data() → [SOCIAL_POST_BATCH]
    ├→ StorageConsumer.save_posts (存帖子)
    └→ AIBriefingConsumer (聚合多平台 + LLM 生成简报)
         │
         ↓ mq.publish(AI_BRIEFING)
         ├→ StorageConsumer.save_briefing (存简报)
         └→ NotificationConsumer.push (推送企微)
```

- AIBriefingConsumer 有多平台聚合逻辑：等 `expected_platforms` 全部到齐后才触发 LLM

### 2.3 Chain 3 — 行情早报

```
MarketBriefingProducer → produce_data() → [MARKET_BRIEFING] → NotificationConsumer.push
```

### 2.4 Chain 4 — 公众号 AI 早报

```
MorningBriefingProducer (从 DB 读存量社交帖子 + 行情数据 → LLM 生成)
    → [AI_BRIEFING]
    ├→ StorageConsumer.save_briefing (存简报)
    └→ NotificationConsumer.push (推送企微)
```

- MorningBriefingProducer 是"边界模糊"的典型：名义上是 producer，但从 DB 读数据（本应是 consumer 的行为），又调 LLM 生成内容（本应是 consumer 的职责）
- 它产出 `AIBriefingMessage`——和 AIBriefingConsumer 产出相同类型

### 2.5 "既是 Consumer 又是 Producer" 的混乱点

| 角色 | 消费 | 内部 mq.publish 或 DB 读取 | 产出 |
|------|------|---------------------------|------|
| VolatilityConsumer | PRICE_DATA | `mq.publish(VOLATILITY_ALERT)` | VolatilityAlertMessage |
| AIBriefingConsumer | SOCIAL_POST_BATCH | `mq.publish(AI_BRIEFING)` | AIBriefingMessage |
| MorningBriefingProducer | — (直接读 DB) | 读 social_store + market_db → 调 LLM | AIBriefingMessage |

现有模型下 producer/consumer 的边界已经模糊：
- consumer 里有 `mq.publish`（隐式变成 producer）
- producer 里有 DB 读取（隐式变成 consumer）
- 链路关系无法从 app.py 看出，必须深入每个类才能追踪

## 3. 现有模块现状

### 3.1 BaseProducer (`producers/base_producer.py`)

- `produce_data()` → 返回 `Sequence[BaseMessage]`
- `_production_wrapper()` 自动遍历结果，逐条 `self.publish_message(msg)` → `mq.publish(channel, msg)`
- 内置 APScheduler 调度器，每个 producer 独立管理自己的 scheduler
- 支持 `run_immediately` / `ignore_schedule` / 定时触发

### 3.2 BaseConsumer (`consumers/base_consumer.py`)

- `process_message(message)` → 返回 `None`（void）
- `start_consumption()` 为每种 MessageType 创建独立线程，调用 `mq.subscribe(channel, handler)`
- 消费者生命周期自管理（start/stop）

### 3.3 MessageQueue (`infra/message_queue.py`)

- Protocol: `publish(channel, message)` + `subscribe(channel, callback)`
- 两种 backend: InMemoryMessageQueue（默认）/ RedisMessageQueue
- InMemory 实现: 每个 subscriber 有独立 Queue，publish 时 deepcopy fan-out
- subscribe 阻塞当前线程

### 3.4 App 布线 (`app.py`)

- `PRODUCER_REGISTRY`: 9 种 producer（含 morning_briefing）
- `setup_producers()`: 按 key 实例化 producer，注入 trigger
- `setup_consumers()`: 硬编码创建 4 个 consumer
- 靠 MessageType channel 隐式串联，无法在 app.py 中看到完整链路

## 4. 改造范围

### 4.0 总览表

| 模块 | 改造类型 | 核心变化 |
|------|---------|---------|
| 新增: Task / Step 抽象 | **新增** | 定义 Task（一条完整链路）和 Step（链路中的一步）；Task 驱动 step 顺序执行，上一步输出→下一步输入；支持分叉 |
| `producers/` 目录 | **重命名/重构** | producer 不再作为独立角色，拆为 Task 的第一个 Step（数据获取步骤）；调度逻辑上移到 Task 层 |
| `consumers/` 目录 | **重命名/重构** | consumer 不再作为独立角色，拆为 Task 中的处理 Step；`process_message` 改为返回结果 |
| `consumers/volatility_consumer.py` | 修改 | 移除内部 `mq.publish`，改为 return alert 结果 |
| `consumers/ai_briefing_consumer.py` | 修改 | 移除内部 `mq.publish`，改为 return briefing 结果 |
| `consumers/storage_consumer.py` | 修改 | 适配 Step 接口，作为透传型步骤 |
| `consumers/notification_consumer.py` | 修改 | 适配 Step 接口，作为终端步骤 |
| `producers/morning_briefing_producer.py` | 修改 | 不再是 producer，变成一个独立的 Task（读 DB → LLM → 通知） |
| `app.py` | **重写** | `setup_producers` + `setup_consumers` → 声明式 Task 定义；启动系统 = 启动 Task |
| `infra/message_queue.py` | **可能移除或简化** | Task 内部用直接调用替代 pub/sub；跨 Task 通信如果需要才保留 mq |
| `models/messages.py` | 可能简化 | MessageType 不再作为路由 key；部分中间 type（VOLATILITY_ALERT）可能不再需要 |

### 4.1 概念映射：现有 → 改造后

| 现有概念 | 改造后 | 说明 |
|---------|-------|------|
| Producer | Task 的第一个 Step | 数据获取步骤，不再独立管理生命周期 |
| Consumer | Task 中的处理 Step | 被 Task 驱动调用，return 结果 |
| `mq.publish` 隐式串联 | Task 链路声明 | 上下游关系在 Task 定义中显式可见 |
| `PRODUCER_REGISTRY` + `setup_consumers` | `TASK_REGISTRY` | 一处定义所有 Task |
| 启动 producer / 启动 consumer | 启动 Task | 一个 Task = 一条完整数据处理链 |

### 4.2 改造后的 Task 定义示意

```python
TASKS = {
    # Task 1: A股价格监控
    "astock_minute": Task(
        trigger=...,
        steps=[
            FetchAStock(frequency="minute"),        # 原 AStockProducer
            StorageStep(),                           # 原 StorageConsumer（存 DB，透传）
            VolatilityStep(),                        # 原 VolatilityConsumer（分析，返回 alert）
            NotifyStep(),                            # 原 NotificationConsumer（推送）
        ],
    ),

    # Task 2: 社交简报
    "social_briefing": Task(
        trigger=...,
        steps=[
            FetchXPosts(),                           # 原 XBriefingProducer
            StorageStep(),                           # 存帖子，透传
            AIBriefingStep(),                        # 原 AIBriefingConsumer（LLM 生成）
            Fork(StorageStep(), NotifyStep()),        # 存简报 + 推送
        ],
    ),

    # Task 3: 行情早报
    "market_briefing": Task(
        trigger=...,
        steps=[
            FetchMarketBriefing(),                   # 原 MarketBriefingProducer
            NotifyStep(),
        ],
    ),

    # Task 4: 公众号 AI 早报
    "morning_briefing": Task(
        trigger=...,
        steps=[
            ReadDBAndGenerateBriefing(),             # 原 MorningBriefingProducer
            Fork(StorageStep(), NotifyStep()),
        ],
    ),
}
```

### 4.3 APScheduler 调度逻辑迁移

**当前**：每个 BaseProducer 内置独立的 `BackgroundScheduler`

**改造后**：调度逻辑上移到 Task 层或 App 层
- 每个 Task 持有自己的 trigger
- 触发时执行完整的 step 链
- 不再需要每个 step 自管理 scheduler

### 4.4 AIBriefingConsumer 多平台聚合的特殊处理

**当前**：AIBriefingConsumer 在内存中 buffer，等 `expected_platforms` 到齐才触发 LLM

**改造后选项**：
- 方案 A：social_briefing Task 本身聚合多个 fetch step 的结果再传给 AIBriefingStep
- 方案 B：保留 AIBriefingStep 内部的 buffer 逻辑（但这会增加 step 的复杂度）
- **倾向方案 A**：Task 层控制聚合，step 保持无状态

## 5. 待确认问题（已确认）

1. **message_queue.py**：保留代码不删，Task 内部用直接调用驱动，mq 暂不使用但不移除
2. **社交简报多平台聚合**：方案 A——Task 层控制聚合，第一步同时 fetch X + Weibo 合并结果，AIBriefingStep 保持无状态
3. **目录重命名**：`producers/` + `consumers/` → `steps/`（或 `tasks/` + `steps/`），按职责命名
4. **错误处理**：Step 抛异常则 Task 中断，Task 层统一 catch + log；个别 Step 内部需降级的自己处理（如 AIBriefingStep 生成失败仍推送错误文案）
5. **Step 复用策略**：共享 Step 类，每个 Task 自己实例化；DB/Notifier 等重资源通过构造函数注入共享实例

## 6. 影响面、风险与回归验证建议

### 6.1 影响面

| 影响范围 | 涉及文件 | 说明 |
|---------|---------|------|
| 核心抽象层 | `base_producer.py`, `base_consumer.py` | 接口变更，所有子类必须适配 |
| 全部 Producer（9 个） | `producers/*.py` | 拆为 Step，移入 `steps/` |
| 全部 Consumer（4 个） | `consumers/*.py` | 拆为 Step，移入 `steps/` |
| 应用入口 | `app.py` | 布线逻辑完全重写 |
| 消息模型 | `models/messages.py` | MessageType 保留但不再用于路由 |
| 基础设施 | `infra/message_queue.py` | 保留代码但 Task 内部不使用 |
| CLI 参数 | `app.py` 的 `parse_args` | `--producers` 改为 `--tasks` 或类似 |
| 配置 | `config/settings.py` 的 `PRODUCER_SCHEDULE` | 改为 `TASK_SCHEDULE` 或 Task 内联 trigger |

### 6.2 风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 重构范围大，步骤遗漏 | 中 | 按 Task 逐条迁移，每迁一条跑一次端到端验证 |
| 多平台聚合迁到 Task 层后行为不一致 | 中 | 单独为 social_briefing Task 写测试，覆盖单平台和双平台场景 |
| NotifyStep 去重逻辑在 Task 隔离后行为变化 | 低 | 不同 Task 的告警 (symbol, frequency) 不重叠，隔离后仍正确 |
| APScheduler 调度上移后遗漏原有配置 | 低 | 对照 `PRODUCER_SCHEDULE` 逐条检查每个 Task 的 trigger |

### 6.3 回归验证建议

- 逐 Task 验证：每个 Task 迁移完后立即用 `--tasks xxx --once` 跑一次，确认数据流端到端通畅
- 重点验证 social_briefing：分别测试只启用 X、只启用 Weibo、同时启用两者
- 确认 NotifyStep 去重：跑 astock_daily 两次，第二次不应重复推送
- 确认 morning_briefing：验证从 DB 读取存量数据 → LLM → 推送的完整链路
