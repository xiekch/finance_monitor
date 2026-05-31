# X 推文 AI 简报 — 设计文档

日期：2026-05-31

## 背景与目标

现有项目是一个基于"Producer → Redis Pub/Sub → Consumer"的多市场行情监控系统，已稳定运行行情抓取与企微告警链路。

新需求：在不破坏现有架构的前提下，新增"X 推文 → AI 过滤 → 推送"的并行链路。
- 数据源：从 X (Twitter) 收集若干关注账号（AI 圈）的推文
- AI 过滤：用 LLM 把这些推文聚合成一份按主题分组的简报
- 推送：通过现有企微 webhook 推送

目标：复用 BaseProducer / BaseConsumer / Redis Pub/Sub / SQLite / WeChatNotifier，通过新增 1 个 producer + 1 个 consumer + 适当扩展现有两个 consumer 的方式落地，避免引入新的基础设施依赖。

## 需求要点（已澄清）

- **数据源**：第三方聚合服务（如 SocialData、TwitterAPI.io 等），抽象成 `SocialClient` 接口，默认实现可后续选定
- **抓取范围**：手动维护的白名单账号列表（在配置中）
- **触发频率**：一天 1–2 次，cron 时段可配置（默认 08:00 / 20:00）
- **AI 输出形态**：全局简报（一次 LLM 调用，按主题分组的 markdown）
- **LLM 选型**：抽象成 `LLMClient` 接口，默认实现为 Anthropic Claude
- **推送渠道**：复用现有企微 webhook
- **AI 过滤的"价值判断"**：交给 prompt（在配置中可调）；不在代码里做评分阈值

## 非目标（YAGNI）

- ❌ 不引入 Redis Streams / Kafka / 任何新消息中间件（一天 1–2 次的场景 Pub/Sub 完全够用）
- ❌ 不引入死信队列、重试队列
- ❌ 不做按账号 / 按推文级别的实时推送（首期只走"全局简报"形态）
- ❌ 不做关键词搜索源（只走白名单 timeline）
- ❌ 不做多渠道分发（不加 Telegram，复用企微即可）
- ❌ 不做 LLM token 预算告警（一天 ≤ 2 次，成本可忽略）
- ❌ 不做账号级速率自适应、并发请求 X API（顺序拉取已足够快）
- ❌ 不在本期写自动化测试（MVP 阶段先打通，测试后续补）

## 方案

新增"X→AI 简报"链路，与行情链路平行，共用 mq / SQLite / 企微 Notifier。

```
                        ┌──────────────────────────── 新增链路 ─────────────────────────────┐
 Cron 08:00/20:00 ──►   XBriefingProducer
                        │  1) 从 SocialPostStore 取每个 handle 的 since_id (= max post_id)
                        │  2) 串行调用 SocialClient.fetch_user_timeline(handle, since_id)
                        │  3) 单账号失败 → 跳过；全空 → 不发消息
                        │  4) 打包成 SocialPostBatchMessage
                        │     publish ──► social_post_batch
                        │        ├──────────────► AIBriefingConsumer
                        │        │                  asyncio.run(LLMClient.summarize(batch))
                        │        │                  publish ──► ai_briefing
                        │        │                                ├──► NotificationConsumer (扩展)
                        │        │                                │      WeChatNotifier.send_markdown(payload.markdown)
                        │        │                                └──► StorageConsumer (扩展)
                        │        │                                       INSERT INTO briefings
                        │        └──────────────► StorageConsumer (扩展)
                        │                          INSERT OR IGNORE INTO social_posts
                        └────────────────────────────────────────────────────────────────────┘

  现有行情链路保持不动：
    *Producers → price_data → VolatilityConsumer → volatility_alert → NotificationConsumer → 企微
                              StorageConsumer
```

### 关键设计要点

1. **新基础设施 = 0**：还是 Pub/Sub，还是 SQLite，还是 APScheduler，还是企微。
2. **新增 2 种 MessageType**：`SOCIAL_POST_BATCH`、`AI_BRIEFING`，命名带前缀，方便和行情消息区分。
3. **2 个新边界抽象**：`SocialClient` / `LLMClient`，都是协议（Protocol），方便换实现。
4. **2 个现有 consumer 增量扩展**：`NotificationConsumer` / `StorageConsumer` 在 `process_message` 里加 elif 分支，不新建消费者类。
5. **`since_id` 增量去重闭环**：StorageConsumer 把推文写入 `social_posts` → 下次 producer 跑时 `SELECT MAX(post_id) WHERE author=?` 拿到 since_id → 自然增量、无需额外状态文件。

## 文件改动清单

```
config/social.py                              # 新增：白名单、cron、prompt、LLM/SocialClient 配置
core/clients/social_client.py                 # 新增：SocialClient 协议 + 默认 HTTP 实现
core/clients/llm_client.py                    # 新增：LLMClient 协议 + AnthropicLLMClient 默认实现
core/producers/x_briefing_producer.py         # 新增
core/consumers/ai_briefing_consumer.py        # 新增
core/consumers/notification_consumer.py       # 修改：加 AI_BRIEFING 分支
core/consumers/storage_consumer.py            # 修改：加 SOCIAL_POST_BATCH / AI_BRIEFING 分支
core/notifiers/wechat_notifier.py             # 修改：补 send_markdown(content) 通用方法 + 4096 截断
core/message_types.py                         # 修改：新增 2 种 MessageType + 2 个 dataclass
models/social_data.py                         # 新增：SocialPost / Briefing dataclass + SocialPostStore (SQLite)
app_producer_consumer.py                      # 修改：PRODUCER_REGISTRY 加 "x_briefing"，按需注入依赖
requirements.txt                              # 修改：新增 anthropic SDK（如选 Claude）
```

## 组件设计

### `SocialClient`（数据源边界）

```python
# core/clients/social_client.py
@dataclass
class SocialPost:
    post_id: str               # 全局唯一，去重主键
    author: str                # @handle
    author_name: str
    text: str
    created_at: datetime
    url: str                   # 原推文链接
    is_retweet: bool
    referenced_url: Optional[str]

class SocialClient(Protocol):
    async def fetch_user_timeline(
        self, handle: str, since_id: Optional[str], limit: int
    ) -> list[SocialPost]: ...

class SocialDataClient(SocialClient):
    """默认实现，对接最终选定的第三方聚合服务"""
    def __init__(self, api_key: str, base_url: str, http_proxy: Optional[str]): ...
```

- 业务代码只依赖协议；具体厂商配置驱动。
- 代理沿用 `config.settings.PROXY`。

### `LLMClient`（AI 边界）

```python
# core/clients/llm_client.py
@dataclass
class BriefingInput:
    posts: list[SocialPost]
    window_hours: int
    user_prompt_extra: Optional[str]   # 个人偏好，如 "我特别关注 multi-agent / 训练效率"

@dataclass
class BriefingOutput:
    markdown: str                       # 直接喂给企微的最终内容
    sections: list[dict]                # [{topic, summary, post_ids}]，结构化存档
    model: str
    input_tokens: int
    output_tokens: int

class LLMClient(Protocol):
    async def summarize(self, payload: BriefingInput) -> BriefingOutput: ...

class AnthropicLLMClient(LLMClient):
    """默认实现，Claude Haiku/Sonnet"""
```

- prompt 模板写在 `config/social.py`，不写死代码。
- 输出 `markdown` 给推送、`sections` 给存档。

### `XBriefingProducer`

```python
class XBriefingProducer(BaseProducer):
    def __init__(self, social: SocialClient, store: SocialPostStore, llm_config: dict, ...):
        super().__init__("XBriefingProducer", ...)

    def create_trigger(self) -> BaseTrigger:
        # CronTrigger，从 config 读 hours，例如 "8,20"
        return CronTrigger(hour=SOCIAL_CONFIG["cron_hours"], minute=0)

    async def produce_data(self) -> Sequence[BaseMessage]:
        all_new = []
        for handle in SOCIAL_CONFIG["whitelist"]:
            since_id = self.store.get_latest_post_id(handle)
            try:
                posts = await self.social.fetch_user_timeline(handle, since_id, limit=50)
            except Exception as e:
                logging.warning(f"[XBriefingProducer] {handle} 拉取失败，跳过: {e}")
                continue
            all_new.extend(posts)
        if not all_new:
            return []                # 空批次直接 short-circuit，不发消息
        return [SocialPostBatchMessage(payload={
            "posts": [asdict(p) for p in all_new],
            "window_hours": SOCIAL_CONFIG["window_hours"],
            "stats": {"total": len(all_new), "by_author": Counter(p.author for p in all_new)},
        }, source=self.producer_name)]
```

### `AIBriefingConsumer`

```python
class AIBriefingConsumer(BaseConsumer):
    def __init__(self, llm: LLMClient):
        super().__init__("AIBriefingConsumer", [MessageType.SOCIAL_POST_BATCH])
        self.llm = llm

    def process_message(self, raw: Dict):
        msg = SocialPostBatchMessage.from_dict(raw)
        posts = [SocialPost(**p) for p in msg.payload["posts"]]
        try:
            result = asyncio.run(self.llm.summarize(BriefingInput(
                posts=posts,
                window_hours=msg.payload["window_hours"],
                user_prompt_extra=SOCIAL_CONFIG.get("user_prompt_extra"),
            )))
            payload = {
                "markdown": result.markdown,
                "sections": result.sections,
                "source_post_count": len(posts),
                "stats": {"model": result.model, "input_tokens": result.input_tokens,
                          "output_tokens": result.output_tokens},
                "degraded": False,
            }
        except Exception as e:
            payload = {
                "markdown": f"📰 AI 简报生成失败\n收到 {len(posts)} 条推文\n错误: {e}",
                "sections": [],
                "source_post_count": len(posts),
                "stats": {},
                "degraded": True,
                "error": str(e),
            }
        mq.publish(MessageType.AI_BRIEFING.value,
                   AIBriefingMessage(payload=payload, source=self.consumer_name).to_dict())
```

- 同步内 `asyncio.run`：与现有 BaseConsumer 同步 handler 风格一致；一天 1–2 次无需线程池。
- LLM 失败也发简报消息，只是 `degraded=true`，用户至少知道 AI 挂了。

### `SocialPostStore` & 持久化

```python
# models/social_data.py
class SocialPostStore:
    def save_posts(self, posts: list[SocialPost]) -> int: ...      # INSERT OR IGNORE
    def get_latest_post_id(self, handle: str) -> Optional[str]: ...
    def save_briefing(self, ...): ...
```

- 复用 `market_data.db`，新增两张表（schema 见 §SQLite Schema）。
- `StorageConsumer` 增加 elif 分支：
  - 收到 `SOCIAL_POST_BATCH` → `save_posts`
  - 收到 `AI_BRIEFING` → `save_briefing`

### `NotificationConsumer` 扩展

```python
elif message_type == MessageType.AI_BRIEFING:
    self.wechat_notifier.send_markdown(message["payload"]["markdown"])
```

- `WeChatNotifier` 补一个通用 `send_markdown(content: str)`，避免简报内容硬塞 alert 模板。
- 4096 字节超长保护：`send_markdown` 内部按字节截断 + "完整版见 SQLite briefings 表"。

### `config/social.py`

```python
SOCIAL_CONFIG = {
    "enabled": True,
    "cron_hours": "8,20",                       # 简报时段
    "window_hours": 12,
    "whitelist": ["karpathy", "sama", "AnthropicAI", ...],
    "fetch_limit_per_user": 50,
    "social_provider": {
        "name": "socialdata",
        "api_key_env": "SOCIALDATA_API_KEY",
        "base_url": "https://api.socialdata.tools",
    },
    "llm_provider": {
        "name": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-4-5",
    },
    "prompt_template": """你是一个 AI 行业资讯编辑...""",
    "user_prompt_extra": "我特别关注 agent / multi-agent / 训练效率",
}
```

- 环境变量名走 `_env` 而非直接存值，沿用现有 settings.py 的 `os.getenv` 风格。
- `enabled=false` 时 `XBriefingProducer` / `AIBriefingConsumer` 都跳过实例化。

## 数据流与消息格式

### 新增 `MessageType`

```python
class MessageType(Enum):
    # ... 现有 ...
    SOCIAL_POST_BATCH = "social_post_batch"   # 新增
    AI_BRIEFING = "ai_briefing"               # 新增
```

### 新增消息类

```python
@dataclass
class SocialPostBatchMessage(BaseMessage):
    """一批新拉到的推文，作为 LLM 输入的原料"""
    # payload: { "window_hours": int, "posts": [...], "stats": {...} }

@dataclass
class AIBriefingMessage(BaseMessage):
    """LLM 已生成的简报"""
    # payload: { "markdown": str, "sections": [...], "source_post_count": int,
    #            "stats": {...}, "degraded": bool, "error": Optional[str] }
```

### 端到端时序（成功路径）

```
T+0ms     APScheduler 触发 XBriefingProducer
T+50ms    Producer 查 social_posts，取每个 handle 的 max(post_id) 作为 since_id
T+1-15s   串行调用 SocialClient.fetch_user_timeline(handle, since_id)
T+~15s    汇总 N 条新推文 → 构造 SocialPostBatchMessage
T+~15s    mq.publish("social_post_batch", batch.to_dict())
            ├──► StorageConsumer  → INSERT OR IGNORE social_posts
            └──► AIBriefingConsumer
                    asyncio.run(LLMClient.summarize(...))
                    mq.publish("ai_briefing", briefing.to_dict())
                       ├──► NotificationConsumer → wechat_notifier.send_markdown(markdown)
                       └──► StorageConsumer       → INSERT briefings
```

**时序约束**：
- StorageConsumer 与 AIBriefingConsumer 是 Pub/Sub 广播，**并行订阅**同一个频道，无先后依赖。
- AI 输入直接走消息 payload，不读 DB，避免"AI consumer 比 storage 跑得快"的种族问题。
- since_id 在**下次** producer 运行时通过 `SELECT MAX(post_id)` 自然刷新。

### 失败路径

| 失败点 | 行为 |
|---|---|
| `SocialClient.fetch_user_timeline` 单账号失败 | producer 内部 try/except，跳过该账号，记 warning |
| 全部账号失败 / 拉到 0 条 | producer 返回空 `messages` 列表，**不 publish**；下次 cron 重试 |
| `LLMClient.summarize` 失败 | publish `AI_BRIEFING` with `degraded=true` 与降级 markdown |
| `WeChatNotifier.send_markdown` 失败 | 仅 error log；简报已落库，可手工补推 |
| `StorageConsumer` 写库失败 | 仅 error log；不影响推送链路（已并行进行） |

### SQLite schema（增量）

```sql
CREATE TABLE IF NOT EXISTS social_posts (
    post_id        TEXT PRIMARY KEY,
    author         TEXT NOT NULL,
    author_name    TEXT,
    text           TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    url            TEXT,
    is_retweet     INTEGER DEFAULT 0,
    referenced_url TEXT,
    fetched_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_social_posts_author_created
    ON social_posts(author, created_at DESC);

CREATE TABLE IF NOT EXISTS briefings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    window_hours    INTEGER,
    source_post_ids TEXT,                  -- JSON array
    markdown        TEXT NOT NULL,
    sections_json   TEXT,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    degraded        INTEGER DEFAULT 0,
    error           TEXT
);
```

- 全部 `IF NOT EXISTS`，启动时由 `models/social_data.py` 自动建表，沿用现有项目风格。
- `social_posts.post_id` 是 PK + UNIQUE，`INSERT OR IGNORE` 自动幂等。

## 错误处理与韧性

### 网络/外部依赖重试

| 调用 | 超时 | 重试 | 兜底 |
|---|---|---|---|
| `SocialClient.fetch_user_timeline` | 单账号 10s | 同步重试 1 次（指数退避 0.5s/2s） | 跳过该账号，其余继续 |
| `LLMClient.summarize` | 60s | 同步重试 1 次 | 走降级简报 |
| `WeChatNotifier.send_markdown` | 10s | 不重试 | 仅 log；简报已落库 |

实现上用裸 `for attempt in range(2)` 实现，不引入 `tenacity` 等新依赖。

### 限流与并发

- 每个 handle 顺序拉取，整体 producer 内串行。30 个账号 × ~0.5s ≈ 15s，远低于 60s 调度容差。
- LLM 单次调用，一天最多 2 次，无需节流。

### 配置缺失/错误

- 启动期 fail-fast：缺 `SOCIALDATA_API_KEY` / `ANTHROPIC_API_KEY` 而 `enabled=true` → `raise` 启动失败
- `enabled=false` → `XBriefingProducer` / `AIBriefingConsumer` 都不实例化（即使 `--producers` 里包含也跳过）
- 白名单为空 → 启动报错

### 幂等与重复

- `social_posts.post_id` UNIQUE + `INSERT OR IGNORE` 保证重复抓取不重复入库
- `briefings` 表只增不改，`degraded=true` 的失败简报也保留，便于事后回查
- `--once` 重跑由于 since_id 已更新，会拉到 0 条 → 空批次 → 不重复推送（理想性质，文档注明）

### 日志策略

- 外部调用三件套：调用 + 耗时 + 状态
  - `[XBriefingProducer] fetch @karpathy since=18xxxx → 7 posts in 540ms`
- LLM 调用额外打 `model / input_tokens / output_tokens`
- 不打推文正文（隐私 + 日志体积）；只打 `post_id` 和首 40 字符

## 测试策略

MVP 暂不实施，后续单独补充。届时建议覆盖：
- 单元：`SocialDataClient` HTTP 重试、`AnthropicLLMClient` prompt 拼装、`XBriefingProducer` 空批次行为、`AIBriefingConsumer` 降级路径、`SocialPostStore` 读写
- 集成：用真 mq + tmp SQLite + fake client 跑通整条链路
- E2E：默认 skip，手工跑过一次再合入，验证中文 prompt 输出质量

## 文档更新

- `README.md` 增加 "X 简报" 章节：`SOCIAL_CONFIG` 字段、必需 env、cron 行为、`--producers x_briefing` 用法
- `.env` 模板补充 `SOCIALDATA_API_KEY` / `ANTHROPIC_API_KEY`

## 顺带的架构改善（不在本期实施，仅备忘）

设计过程中讨论过的现有架构可改善点，记录但不在本期落地：

1. **Redis Pub/Sub 换 Streams**：当前 fire-and-forget，掉一条 LLM 结果就白调用。一天 1–2 次的简报场景容忍度高，暂不需要换；将来若加"实时高频抓取 + 单条推文实时推送"，再考虑迁移
2. **`MessageType` 命名加业务前缀**：现有 `PRICE_DATA` 改 `MARKET_PRICE_DATA`，让多业务共存更清晰。本期新增的 `SOCIAL_POST_BATCH` / `AI_BRIEFING` 已带前缀；老消息类型重命名留作后续
3. **配置分文件**：本期新增 `config/social.py` 已经是这个方向。之后可顺势把现有 `MONITOR_CONFIG` 拆到 `config/market.py`

## 推出顺序（实施阶段）

1. `config/social.py` + `models/social_data.py`（schema、Store）
2. `core/message_types.py`（2 种新 MessageType + 2 个 dataclass）
3. `core/clients/social_client.py` + `core/clients/llm_client.py`（含默认实现）
4. `core/notifiers/wechat_notifier.py` 补 `send_markdown`
5. `core/producers/x_briefing_producer.py`
6. `core/consumers/ai_briefing_consumer.py`
7. `core/consumers/storage_consumer.py` / `core/consumers/notification_consumer.py` 扩展分支
8. `app_producer_consumer.py` 注册 `"x_briefing"` + 依赖注入
9. README + .env 模板
10. 手工 dry-run 验证
