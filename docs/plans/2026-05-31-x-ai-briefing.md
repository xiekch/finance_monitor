# X 推文 AI 简报 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-executing-plans to implement this plan task-by-task.

**Goal:** 在不动现有行情链路的前提下，新增"X 推文 → LLM 聚合简报 → 企微推送"的 producer/consumer 链路，每天 cron 触发 1–2 次。

**Architecture:** 复用 `BaseProducer` / `BaseConsumer` / Redis Pub/Sub / SQLite / `WeChatNotifier`。新增 1 个 producer (`XBriefingProducer`) + 1 个 consumer (`AIBriefingConsumer`)，扩展现有 `StorageConsumer` / `NotificationConsumer` 各自的 `process_message` 加 elif 分支。两个边界（外部数据源、LLM）抽象成 Protocol：`SocialClient` / `LLMClient`，默认实现可后期换。新增 2 种 `MessageType`：`SOCIAL_POST_BATCH`、`AI_BRIEFING`。

**Tech Stack:** Python 3.9+ / Redis Pub/Sub / APScheduler / SQLite / Anthropic Python SDK / requests / dotenv

**设计文档：** `docs/plans/2026-05-31-x-ai-briefing-design.md`（已与用户确认）

---

## 重要约定

- **MVP 阶段不写自动化测试**（用户决定）。每个 Task 用"手工运行命令并目视检查"代替。
- **Commit 粒度由执行者自定**：每个 Task 末尾给出建议的 commit 命令，但是否执行由执行者决定。本计划生成时 git 工作树有未相关修改，提交前请确认 stage 范围。
- **第三方 X 聚合服务尚未最终选定**：默认实现按 `socialdata.tools` 风格（GET `/twitter/user/{handle}/tweets`）写一个最小 HTTP 适配，便于后期替换。Task 4 注明这一点。
- **YAGNI**：不写测试，不引入 tenacity / pydantic / httpx 等新依赖；用 stdlib + 项目已有的 requests / anthropic SDK。
- **每个 Task 在改动后用提供的命令做最小自检**（import 是否成功、新表是否建出、配置是否能加载等）。

---

## Task 1: 创建配置文件 `config/social.py`

**Files:**
- Create: `config/social.py`
- Modify: `.env`（用户私有，不入库；本步只在文档里指出新 env 名）

**Step 1: 写新配置文件**

```python
# config/social.py
"""X 推文 AI 简报相关配置。所有运行时参数集中在此，避免污染 settings.py。"""
import os

SOCIAL_CONFIG = {
    # 总开关：False 时 XBriefingProducer / AIBriefingConsumer 不实例化
    "enabled": True,

    # 简报 cron 时段（小时，逗号分隔）
    "cron_hours": "8,20",
    # 每次简报覆盖的回看窗口（仅作为 LLM prompt 上下文，不限制 since_id 增量）
    "window_hours": 12,

    # 关注的 X 账号白名单（不带 @）
    "whitelist": [
        # "karpathy",
        # "sama",
        # "AnthropicAI",
    ],
    # 单账号单次拉取上限
    "fetch_limit_per_user": 50,

    # X 数据源（默认 socialdata.tools，按最终选定服务再调整 base_url 与 client 实现）
    "social_provider": {
        "name": "socialdata",
        "api_key_env": "SOCIALDATA_API_KEY",
        "base_url": "https://api.socialdata.tools",
        "timeout_sec": 10,
    },

    # LLM
    "llm_provider": {
        "name": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-4-5",
        "max_tokens": 2048,
        "timeout_sec": 60,
    },

    # Prompt 主体（占位，后续可按需精修）
    "prompt_template": (
        "你是一个 AI 行业资讯编辑。下面是过去 {window_hours} 小时内来自我关注的"
        "AI 圈作者的若干条 X 推文（已按时间倒序）。请：\n"
        "1) 跳过纯营销、转推无新增评论、互动闲聊；\n"
        "2) 把剩余有信息量的内容按主题分组（每组 1–3 条）；\n"
        "3) 每组用一句话概括主旨，再列原始作者 + 链接；\n"
        "4) 用 Markdown 输出，控制在 {max_chars} 字符以内（企微限制）。\n\n"
        "用户偏好：{user_prompt_extra}\n\n"
        "推文清单：\n{posts_block}"
    ),
    "user_prompt_extra": "我特别关注 agent / multi-agent / 训练效率",
    # 推送给企微的硬上限（4096 字节内安全冗余）
    "push_max_chars": 3500,
}


def assert_social_env_ready():
    """启动期 fail-fast：enabled=true 但缺关键 env 时立即报错。"""
    if not SOCIAL_CONFIG["enabled"]:
        return
    missing = []
    for prov_key in ("social_provider", "llm_provider"):
        env_name = SOCIAL_CONFIG[prov_key]["api_key_env"]
        if not os.getenv(env_name):
            missing.append(env_name)
    if missing:
        raise RuntimeError(
            f"SOCIAL_CONFIG.enabled=True 但以下环境变量缺失: {missing}；"
            f"请在 .env 中设置或将 enabled 设为 False。"
        )
    if not SOCIAL_CONFIG["whitelist"]:
        raise RuntimeError(
            "SOCIAL_CONFIG.whitelist 为空；空跑会浪费 LLM 配额，请至少配置 1 个账号。"
        )
```

**Step 2: 验证模块可导入**

Run:
```bash
python -c "from config.social import SOCIAL_CONFIG, assert_social_env_ready; print(list(SOCIAL_CONFIG.keys()))"
```
Expected: 打印 `['enabled', 'cron_hours', 'window_hours', 'whitelist', ...]`，无报错。

**Step 3: 验证 fail-fast 行为（白名单为空）**

Run:
```bash
python -c "from config.social import assert_social_env_ready; assert_social_env_ready()"
```
Expected: `RuntimeError: SOCIAL_CONFIG.whitelist 为空; ...`

**Step 4: 提交（可选）**

```bash
git add config/social.py
git commit -m "feat(social): add SOCIAL_CONFIG and env precheck"
```

---

## Task 2: 数据模型 `models/social_data.py`

**Files:**
- Create: `models/social_data.py`

**Step 1: 写 dataclass + Store**

```python
# models/social_data.py
"""X 推文 / AI 简报的数据模型与 SQLite 持久化层。复用 market_data.db。"""
import json
import sqlite3
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any

from config.settings import DATABASE_CONFIG


@dataclass
class SocialPost:
    post_id: str          # 全局唯一，去重主键
    author: str           # @handle（不带 @）
    author_name: str
    text: str
    created_at: str       # ISO8601 字符串，避免 datetime 跨进程序列化的坑
    url: str
    is_retweet: bool = False
    referenced_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SocialPost":
        return cls(**d)


@dataclass
class Briefing:
    created_at: str          # ISO
    window_hours: int
    source_post_ids: List[str]
    markdown: str
    sections_json: str       # 结构化 sections，json.dumps 后存
    model: str
    input_tokens: int
    output_tokens: int
    degraded: bool
    error: Optional[str]


class SocialPostStore:
    """SQLite 适配层。所有方法线程安全（每次 connect/close）。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_CONFIG["path"]
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_schema(self):
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
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
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_social_posts_author_created
                    ON social_posts(author, created_at DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS briefings (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at      TEXT NOT NULL,
                    window_hours    INTEGER,
                    source_post_ids TEXT,
                    markdown        TEXT NOT NULL,
                    sections_json   TEXT,
                    model           TEXT,
                    input_tokens    INTEGER,
                    output_tokens   INTEGER,
                    degraded        INTEGER DEFAULT 0,
                    error           TEXT
                )
            """)
            conn.commit()

    def save_posts(self, posts: List[SocialPost]) -> int:
        """INSERT OR IGNORE，返回实际新增条数。"""
        if not posts:
            return 0
        now_iso = datetime.now().isoformat()
        rows = [
            (p.post_id, p.author, p.author_name, p.text, p.created_at, p.url,
             1 if p.is_retweet else 0, p.referenced_url, now_iso)
            for p in posts
        ]
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            before = conn.total_changes
            cur.executemany("""
                INSERT OR IGNORE INTO social_posts
                (post_id, author, author_name, text, created_at, url,
                 is_retweet, referenced_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
            return conn.total_changes - before

    def get_latest_post_id(self, author: str) -> Optional[str]:
        """X 的 post_id 是 snowflake，单调递增，按 ID 排序比按时间稳。"""
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT post_id FROM social_posts
                WHERE author = ?
                ORDER BY CAST(post_id AS INTEGER) DESC
                LIMIT 1
            """, (author,))
            row = cur.fetchone()
            return row[0] if row else None

    def save_briefing(self, briefing: Briefing) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO briefings
                (created_at, window_hours, source_post_ids, markdown, sections_json,
                 model, input_tokens, output_tokens, degraded, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                briefing.created_at, briefing.window_hours,
                json.dumps(briefing.source_post_ids), briefing.markdown,
                briefing.sections_json, briefing.model,
                briefing.input_tokens, briefing.output_tokens,
                1 if briefing.degraded else 0, briefing.error,
            ))
            conn.commit()
            return cur.lastrowid
```

**Step 2: 验证表能建出来**

Run:
```bash
python -c "from models.social_data import SocialPostStore; SocialPostStore(); print('ok')"
sqlite3 market_data.db ".schema social_posts"
sqlite3 market_data.db ".schema briefings"
```
Expected: 输出两张表的 CREATE 语句；无异常。

**Step 3: 验证幂等 + since_id**

Run:
```bash
python <<'PY'
from models.social_data import SocialPostStore, SocialPost
s = SocialPostStore()
posts = [
    SocialPost(post_id="100", author="karpathy", author_name="Andrej",
               text="hello", created_at="2026-05-31T10:00:00", url="https://x/1"),
    SocialPost(post_id="101", author="karpathy", author_name="Andrej",
               text="world", created_at="2026-05-31T10:01:00", url="https://x/2"),
]
print("inserted", s.save_posts(posts))
print("inserted again (should be 0)", s.save_posts(posts))
print("latest", s.get_latest_post_id("karpathy"))
PY
```
Expected: `inserted 2` / `inserted again (should be 0) 0` / `latest 101`。

**Step 4: 提交（可选）**

```bash
git add models/social_data.py
git commit -m "feat(social): add SocialPost / Briefing dataclasses and SQLite store"
```

---

## Task 3: 扩展 `core/message_types.py`

**Files:**
- Modify: `core/message_types.py`

**Step 1: 加 2 种 MessageType + 2 个消息 dataclass**

在 `MessageType` 枚举末尾追加：

```python
    SOCIAL_POST_BATCH = "social_post_batch"   # 一批新拉到的推文
    AI_BRIEFING = "ai_briefing"               # LLM 已生成的简报
```

在文件末尾追加两个消息类：

```python
@dataclass
class SocialPostBatchMessage(BaseMessage):
    """一批新拉到的推文，作为 LLM 输入的原料。"""
    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type: MessageType = MessageType.SOCIAL_POST_BATCH,
    ):
        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )


@dataclass
class AIBriefingMessage(BaseMessage):
    """LLM 已生成的简报。"""
    def __init__(
        self,
        payload: Dict[str, Any],
        source: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
        message_type: MessageType = MessageType.AI_BRIEFING,
    ):
        super().__init__(
            message_type=message_type,
            timestamp=timestamp,
            source=source,
            payload=payload,
            message_id=message_id,
        )
```

**Step 2: 验证 round-trip**

Run:
```bash
python <<'PY'
from core.message_types import SocialPostBatchMessage, AIBriefingMessage, MessageType
m = SocialPostBatchMessage(payload={"posts": [], "window_hours": 12}, source="x")
d = m.to_dict()
assert d["message_type"] == "social_post_batch"
m2 = SocialPostBatchMessage.from_dict(d)
assert m2.payload == m.payload
print("ok", MessageType.SOCIAL_POST_BATCH.value, MessageType.AI_BRIEFING.value)
PY
```
Expected: `ok social_post_batch ai_briefing`。

**Step 3: 提交（可选）**

```bash
git add core/message_types.py
git commit -m "feat(social): add SOCIAL_POST_BATCH and AI_BRIEFING message types"
```

---

## Task 4: `SocialClient` 协议 + 默认实现

**Files:**
- Create: `core/clients/__init__.py`（空文件）
- Create: `core/clients/social_client.py`

> ⚠️ **占位实现**：以下 `SocialDataClient` 假设第三方服务返回 `{"tweets": [...]}` 风格 JSON。最终选定服务后需对照其文档调整字段映射；接口 `SocialClient` 不变。

**Step 1: 写客户端**

```python
# core/clients/__init__.py
```

```python
# core/clients/social_client.py
"""X 推文抓取边界。业务代码只依赖 SocialClient 协议。"""
import logging
import time
from typing import List, Optional, Protocol

import requests

from models.social_data import SocialPost


class SocialClient(Protocol):
    async def fetch_user_timeline(
        self, handle: str, since_id: Optional[str], limit: int
    ) -> List[SocialPost]: ...


class SocialDataClient:
    """默认实现，按 socialdata.tools 风格 HTTP API 适配；
    最终选定第三方服务后只需改这个类的字段映射。"""

    def __init__(self, api_key: str, base_url: str, timeout_sec: int = 10):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_sec
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })

    async def fetch_user_timeline(
        self, handle: str, since_id: Optional[str], limit: int
    ) -> List[SocialPost]:
        # async 接口里走同步 HTTP，调用方一天 1–2 次，不值得引入 httpx。
        url = f"{self.base_url}/twitter/user/{handle}/tweets"
        params = {"limit": limit}
        if since_id:
            params["since_id"] = since_id

        last_err: Optional[Exception] = None
        for attempt in range(2):
            t0 = time.time()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                posts = [self._parse(t) for t in payload.get("tweets", [])]
                ms = int((time.time() - t0) * 1000)
                logging.info(
                    f"[SocialDataClient] fetch @{handle} since={since_id} → {len(posts)} posts in {ms}ms"
                )
                return posts
            except Exception as e:
                last_err = e
                wait = 0.5 * (2 ** attempt)
                logging.warning(
                    f"[SocialDataClient] fetch @{handle} attempt {attempt + 1} failed: {e}; retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"fetch_user_timeline @{handle} failed: {last_err}")

    @staticmethod
    def _parse(t: dict) -> SocialPost:
        """字段映射；按最终服务的实际字段名调整这里即可。"""
        return SocialPost(
            post_id=str(t.get("id_str") or t.get("id")),
            author=t.get("user", {}).get("screen_name", ""),
            author_name=t.get("user", {}).get("name", ""),
            text=t.get("full_text") or t.get("text") or "",
            created_at=t.get("tweet_created_at") or t.get("created_at") or "",
            url=t.get("url") or f"https://x.com/i/status/{t.get('id_str')}",
            is_retweet=bool(t.get("retweeted_status")),
            referenced_url=(t.get("retweeted_status") or {}).get("url"),
        )


def build_default_social_client() -> SocialClient:
    import os
    from config.social import SOCIAL_CONFIG
    cfg = SOCIAL_CONFIG["social_provider"]
    return SocialDataClient(
        api_key=os.getenv(cfg["api_key_env"], ""),
        base_url=cfg["base_url"],
        timeout_sec=cfg["timeout_sec"],
    )
```

**Step 2: 验证模块可导入 + 工厂能跑（不发请求）**

Run:
```bash
python -c "from core.clients.social_client import build_default_social_client, SocialDataClient; print(SocialDataClient.__name__)"
```
Expected: `SocialDataClient`。

**Step 3: 提交（可选）**

```bash
git add core/clients/__init__.py core/clients/social_client.py
git commit -m "feat(social): add SocialClient protocol and SocialDataClient default impl"
```

---

## Task 5: `LLMClient` 协议 + Anthropic 默认实现

**Files:**
- Create: `core/clients/llm_client.py`
- Modify: `requirements.txt`（加 `anthropic`）

**Step 1: 加依赖**

读 `requirements.txt` 后追加 `anthropic` 行（保持字母序或追加在末尾，看现有风格）。

Run:
```bash
pip install anthropic
```
Expected: 成功安装。

**Step 2: 写客户端**

```python
# core/clients/llm_client.py
"""LLM 边界。业务代码只依赖 LLMClient 协议。"""
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, Dict, Any

from models.social_data import SocialPost


@dataclass
class BriefingInput:
    posts: List[SocialPost]
    window_hours: int
    user_prompt_extra: Optional[str]
    max_chars: int


@dataclass
class BriefingOutput:
    markdown: str
    sections: List[Dict[str, Any]]   # [{topic, summary, post_ids}]
    model: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    async def summarize(self, payload: BriefingInput) -> BriefingOutput: ...


class AnthropicLLMClient:
    """默认实现：Claude Haiku/Sonnet via anthropic SDK。"""

    def __init__(self, api_key: str, model: str, max_tokens: int,
                 prompt_template: str, timeout_sec: int = 60):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key, timeout=timeout_sec)
        self.model = model
        self.max_tokens = max_tokens
        self.prompt_template = prompt_template

    async def summarize(self, payload: BriefingInput) -> BriefingOutput:
        prompt = self._render_prompt(payload)
        last_err: Optional[Exception] = None
        for attempt in range(2):
            t0 = time.time()
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                ms = int((time.time() - t0) * 1000)
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                logging.info(
                    f"[AnthropicLLMClient] model={self.model} "
                    f"in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
                    f"elapsed={ms}ms"
                )
                return BriefingOutput(
                    markdown=text.strip(),
                    sections=[],   # MVP 不强制结构化解析；可在 prompt 中要求 JSON 后再补
                    model=self.model,
                    input_tokens=resp.usage.input_tokens,
                    output_tokens=resp.usage.output_tokens,
                )
            except Exception as e:
                last_err = e
                wait = 1.0 * (2 ** attempt)
                logging.warning(
                    f"[AnthropicLLMClient] attempt {attempt + 1} failed: {e}; retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"LLM summarize failed: {last_err}")

    def _render_prompt(self, payload: BriefingInput) -> str:
        posts_block = "\n\n".join(
            f"[{p.author}] {p.created_at}\n{p.text}\n{p.url}"
            for p in payload.posts
        )
        return self.prompt_template.format(
            window_hours=payload.window_hours,
            user_prompt_extra=payload.user_prompt_extra or "",
            max_chars=payload.max_chars,
            posts_block=posts_block,
        )


def build_default_llm_client() -> LLMClient:
    import os
    from config.social import SOCIAL_CONFIG
    llm_cfg = SOCIAL_CONFIG["llm_provider"]
    return AnthropicLLMClient(
        api_key=os.getenv(llm_cfg["api_key_env"], ""),
        model=llm_cfg["model"],
        max_tokens=llm_cfg["max_tokens"],
        prompt_template=SOCIAL_CONFIG["prompt_template"],
        timeout_sec=llm_cfg["timeout_sec"],
    )
```

**Step 3: 验证模块可导入**

Run:
```bash
python -c "from core.clients.llm_client import build_default_llm_client, AnthropicLLMClient; print(AnthropicLLMClient.__name__)"
```
Expected: `AnthropicLLMClient`。

**Step 4: 提交（可选）**

```bash
git add core/clients/llm_client.py requirements.txt
git commit -m "feat(social): add LLMClient protocol and Anthropic default impl"
```

---

## Task 6: 给 `WeChatNotifier` 加通用 `send_markdown`

**Files:**
- Modify: `core/notifiers/wechat_notifier.py`

**Step 1: 增加方法**

在 `WeChatNotifier` 类中追加：

```python
    def send_markdown(self, content: str, max_chars: int = 3500) -> bool:
        """发送任意 markdown 内容。超长按字符截断并附提示。"""
        if not content:
            logging.warning("[WeChatNotifier] send_markdown: 空内容，跳过发送")
            return False
        body = content
        if len(body) > max_chars:
            body = body[:max_chars] + "\n\n_（内容过长已截断，完整版见 SQLite briefings 表）_"
        headers = {"Content-Type": "application/json"}
        data = {"msgtype": "markdown", "markdown": {"content": body}}
        try:
            response = self.session.post(
                self.webhook_url, headers=headers, data=json.dumps(data), timeout=10,
            )
            if response.status_code == 200:
                logging.info(f"[WeChatNotifier] markdown 发送成功，长度={len(body)}")
                return True
            logging.error(
                f"[WeChatNotifier] markdown 发送失败: {response.status_code} - {response.text}"
            )
            return False
        except Exception as e:
            logging.error(f"[WeChatNotifier] markdown 发送异常: {e}")
            return False
```

**Step 2: 验证 import 正常**

Run:
```bash
python -c "from core.notifiers.wechat_notifier import WeChatNotifier; print(hasattr(WeChatNotifier, 'send_markdown'))"
```
Expected: `True`。

**Step 3: 提交（可选）**

```bash
git add core/notifiers/wechat_notifier.py
git commit -m "feat(notifier): add generic send_markdown with length truncation"
```

---

## Task 7: `XBriefingProducer`

**Files:**
- Create: `core/producers/x_briefing_producer.py`

**Step 1: 写 producer**

```python
# core/producers/x_briefing_producer.py
import asyncio
import logging
from collections import Counter
from dataclasses import asdict
from typing import Sequence, List, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.base import BaseTrigger

from core.producers.base_producer import BaseProducer
from core.message_types import BaseMessage, SocialPostBatchMessage
from core.clients.social_client import SocialClient, build_default_social_client
from models.social_data import SocialPostStore, SocialPost
from config.social import SOCIAL_CONFIG


class XBriefingProducer(BaseProducer):
    def __init__(
        self,
        social: Optional[SocialClient] = None,
        store: Optional[SocialPostStore] = None,
        run_immediately: bool = False,
        ignore_schedule: bool = False,
    ):
        super().__init__(
            "XBriefingProducer",
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
        )
        self.social = social or build_default_social_client()
        self.store = store or SocialPostStore()

    def create_trigger(self) -> BaseTrigger:
        return CronTrigger(hour=SOCIAL_CONFIG["cron_hours"], minute=0)

    async def produce_data(self) -> Sequence[BaseMessage]:
        whitelist: List[str] = SOCIAL_CONFIG["whitelist"]
        limit: int = SOCIAL_CONFIG["fetch_limit_per_user"]
        all_new: List[SocialPost] = []

        for handle in whitelist:
            since_id = self.store.get_latest_post_id(handle)
            try:
                posts = await self.social.fetch_user_timeline(handle, since_id, limit)
            except Exception as e:
                logging.warning(f"[XBriefingProducer] @{handle} fetch failed, skip: {e}")
                continue
            all_new.extend(posts)

        if not all_new:
            logging.info("[XBriefingProducer] no new posts, skip publishing")
            return []

        payload = {
            "posts": [asdict(p) for p in all_new],
            "window_hours": SOCIAL_CONFIG["window_hours"],
            "stats": {
                "total": len(all_new),
                "by_author": dict(Counter(p.author for p in all_new)),
            },
        }
        return [SocialPostBatchMessage(payload=payload, source=self.producer_name)]
```

**Step 2: 验证模块可导入 + trigger 构造**

Run:
```bash
python <<'PY'
from core.producers.x_briefing_producer import XBriefingProducer
# 不真实例化（会建 socialclient）；只检查类
print("class ok:", XBriefingProducer.__name__)
PY
```
Expected: `class ok: XBriefingProducer`。

**Step 3: 提交（可选）**

```bash
git add core/producers/x_briefing_producer.py
git commit -m "feat(social): add XBriefingProducer with since_id incremental fetch"
```

---

## Task 8: `AIBriefingConsumer`

**Files:**
- Create: `core/consumers/ai_briefing_consumer.py`

**Step 1: 写 consumer**

```python
# core/consumers/ai_briefing_consumer.py
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from core.consumers.base_consumer import BaseConsumer
from core.message_queue import mq
from core.message_types import (
    MessageType,
    SocialPostBatchMessage,
    AIBriefingMessage,
)
from core.clients.llm_client import (
    LLMClient,
    BriefingInput,
    build_default_llm_client,
)
from models.social_data import SocialPost
from config.social import SOCIAL_CONFIG


class AIBriefingConsumer(BaseConsumer):
    def __init__(self, llm: Optional[LLMClient] = None):
        super().__init__("AIBriefingConsumer", [MessageType.SOCIAL_POST_BATCH])
        self.llm = llm or build_default_llm_client()

    def process_message(self, message: Dict):
        batch = SocialPostBatchMessage.from_dict(message)
        posts = [SocialPost.from_dict(p) for p in batch.payload.get("posts", [])]
        if not posts:
            logging.warning(f"[{self.consumer_name}] empty batch received, skip")
            return

        bi = BriefingInput(
            posts=posts,
            window_hours=batch.payload.get("window_hours", SOCIAL_CONFIG["window_hours"]),
            user_prompt_extra=SOCIAL_CONFIG.get("user_prompt_extra"),
            max_chars=SOCIAL_CONFIG["push_max_chars"],
        )

        try:
            result = asyncio.run(self.llm.summarize(bi))
            payload = {
                "markdown": result.markdown,
                "sections": result.sections,
                "source_post_count": len(posts),
                "source_post_ids": [p.post_id for p in posts],
                "stats": {
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                "degraded": False,
                "error": None,
                "created_at": datetime.now().isoformat(),
                "window_hours": bi.window_hours,
            }
        except Exception as e:
            logging.error(f"[{self.consumer_name}] LLM summarize failed: {e}", exc_info=True)
            by_author = batch.payload.get("stats", {}).get("by_author", {})
            md = (
                f"📰 AI 简报生成失败\n\n"
                f"收到 {len(posts)} 条推文（{by_author}）\n"
                f"错误: {e}\n\n"
                f"原始推文 ID 已写入 SQLite social_posts 表。"
            )
            payload = {
                "markdown": md,
                "sections": [],
                "source_post_count": len(posts),
                "source_post_ids": [p.post_id for p in posts],
                "stats": {},
                "degraded": True,
                "error": str(e),
                "created_at": datetime.now().isoformat(),
                "window_hours": bi.window_hours,
            }

        out = AIBriefingMessage(payload=payload, source=self.consumer_name)
        mq.publish(MessageType.AI_BRIEFING.value, out.to_dict())
        logging.info(
            f"[{self.consumer_name}] published AI_BRIEFING degraded={payload['degraded']} "
            f"posts={len(posts)}"
        )
```

**Step 2: 验证模块可导入**

Run:
```bash
python -c "from core.consumers.ai_briefing_consumer import AIBriefingConsumer; print(AIBriefingConsumer.__name__)"
```
Expected: `AIBriefingConsumer`。

**Step 3: 提交（可选）**

```bash
git add core/consumers/ai_briefing_consumer.py
git commit -m "feat(social): add AIBriefingConsumer with degraded-fallback path"
```

---

## Task 9: 扩展 `StorageConsumer` 处理 social/briefing

**Files:**
- Modify: `core/consumers/storage_consumer.py`

**Step 1: 重构 process_message 为分发器**

完整改写文件：

```python
# core/consumers/storage_consumer.py
import json
import logging
from datetime import datetime
from typing import Dict

from core.consumers.base_consumer import BaseConsumer
from core.message_types import (
    MessageType,
    PriceDataMessage,
    SocialPostBatchMessage,
    AIBriefingMessage,
)
from models.market_data import PriceData, MarketDataDB
from models.social_data import SocialPost, SocialPostStore, Briefing


class StorageConsumer(BaseConsumer):
    """数据存储消费者：行情 + 推文 + 简报"""

    def __init__(self):
        super().__init__("StorageConsumer", [
            MessageType.PRICE_DATA,
            MessageType.HISTORICAL_PRICE_DATA,
            MessageType.SOCIAL_POST_BATCH,
            MessageType.AI_BRIEFING,
        ])
        self.db = MarketDataDB()
        self.social_store = SocialPostStore()

    def process_message(self, message: Dict):
        mt = MessageType(message["message_type"])
        if mt in (MessageType.PRICE_DATA, MessageType.HISTORICAL_PRICE_DATA):
            self._handle_price(message)
        elif mt == MessageType.SOCIAL_POST_BATCH:
            self._handle_social_batch(message)
        elif mt == MessageType.AI_BRIEFING:
            self._handle_briefing(message)

    def _handle_price(self, message: Dict):
        price_message = PriceDataMessage.from_dict(message)
        price_data = PriceData(**price_message.payload)
        if self.db.save_price_data(price_data):
            logging.info(f"[{self.consumer_name}] 数据已保存: {price_data.symbol} {price_data}")
        else:
            logging.info(f"[{self.consumer_name}] 数据已存在，无需保存: {price_data.symbol} {price_data}")

    def _handle_social_batch(self, message: Dict):
        msg = SocialPostBatchMessage.from_dict(message)
        posts = [SocialPost.from_dict(p) for p in msg.payload.get("posts", [])]
        n = self.social_store.save_posts(posts)
        logging.info(
            f"[{self.consumer_name}] social_posts batch saved: "
            f"new={n} total_in_batch={len(posts)}"
        )

    def _handle_briefing(self, message: Dict):
        msg = AIBriefingMessage.from_dict(message)
        p = msg.payload
        briefing = Briefing(
            created_at=p.get("created_at") or datetime.now().isoformat(),
            window_hours=p.get("window_hours", 0),
            source_post_ids=p.get("source_post_ids", []),
            markdown=p.get("markdown", ""),
            sections_json=json.dumps(p.get("sections", [])),
            model=(p.get("stats") or {}).get("model", ""),
            input_tokens=(p.get("stats") or {}).get("input_tokens", 0),
            output_tokens=(p.get("stats") or {}).get("output_tokens", 0),
            degraded=bool(p.get("degraded", False)),
            error=p.get("error"),
        )
        bid = self.social_store.save_briefing(briefing)
        logging.info(
            f"[{self.consumer_name}] briefing saved id={bid} degraded={briefing.degraded}"
        )
```

**Step 2: 验证模块可导入**

Run:
```bash
python -c "from core.consumers.storage_consumer import StorageConsumer; c = StorageConsumer(); print(c.message_types)"
```
Expected: 列表中包含 `MessageType.SOCIAL_POST_BATCH` 和 `MessageType.AI_BRIEFING`。

**Step 3: 提交（可选）**

```bash
git add core/consumers/storage_consumer.py
git commit -m "feat(storage): handle SOCIAL_POST_BATCH and AI_BRIEFING in StorageConsumer"
```

---

## Task 10: 扩展 `NotificationConsumer` 处理 briefing

**Files:**
- Modify: `core/consumers/notification_consumer.py`

**Step 1: 增加 elif 分支 + 订阅类型**

修改 `__init__` 让消费者订阅 `AI_BRIEFING`，修改 `process_message` 加分支：

```python
# core/consumers/notification_consumer.py
from typing import Dict

from .base_consumer import BaseConsumer
from core.message_types import (
    BaseMessage,
    VolatilityAlertMessage,
    SystemEventMessage,
    AIBriefingMessage,
    MessageType,
)
from core.notifiers.wechat_notifier import WeChatNotifier
from config.social import SOCIAL_CONFIG
import logging


class NotificationConsumer(BaseConsumer):
    """通知发送消费者"""

    def __init__(self):
        super().__init__("NotificationConsumer", [
            MessageType.VOLATILITY_ALERT,
            MessageType.AI_BRIEFING,
            # MessageType.SYSTEM_EVENT
        ])
        self.wechat_notifier = WeChatNotifier()

    def process_message(self, message: Dict):
        message_type = MessageType(message["message_type"])
        if message_type == MessageType.VOLATILITY_ALERT:
            self._handle_volatility_alert(VolatilityAlertMessage.from_dict(message))
        elif message_type == MessageType.SYSTEM_EVENT:
            self._handle_system_event(SystemEventMessage.from_dict(message))
        elif message_type == MessageType.AI_BRIEFING:
            self._handle_briefing(AIBriefingMessage.from_dict(message))

    def _handle_volatility_alert(self, message: BaseMessage):
        alert_data = message.payload
        from models.market_data import VolatilityAlert
        from datetime import datetime

        alert = VolatilityAlert(
            symbol=alert_data["symbol"],
            name=alert_data["name"],
            frequency=alert_data["frequency"],
            current_change=alert_data["current_change"],
            threshold=alert_data["threshold"],
            current_price=alert_data["current_price"],
            previous_price=alert_data["previous_price"],
            timestamp=datetime.fromisoformat(alert_data["timestamp"]),
        )
        if self.wechat_notifier.send_alert(alert):
            logging.info(f"[{self.consumer_name}] 告警通知发送成功: {alert.name}")
        else:
            logging.error(f"[{self.consumer_name}] 告警通知发送失败: {alert.name}")

    def _handle_system_event(self, message: BaseMessage):
        event_type = message.payload["event_type"]
        event_data = message.payload["event_data"]
        if event_type == "system_start":
            self.wechat_notifier.send_test_message()
            logging.info(f"[{self.consumer_name}] 系统启动通知已发送")
        elif event_type == "system_shutdown":
            shutdown_message = f"🛑 市场监控系统已关闭\n时间: {event_data.get('timestamp', 'N/A')}"
            self.wechat_notifier._send_wecom_message(shutdown_message)
            logging.info(f"[{self.consumer_name}] 系统关闭通知已发送")

    def _handle_briefing(self, message: BaseMessage):
        markdown = message.payload.get("markdown", "")
        ok = self.wechat_notifier.send_markdown(
            markdown, max_chars=SOCIAL_CONFIG["push_max_chars"]
        )
        degraded = message.payload.get("degraded")
        if ok:
            logging.info(f"[{self.consumer_name}] AI 简报推送成功 degraded={degraded}")
        else:
            logging.error(f"[{self.consumer_name}] AI 简报推送失败 degraded={degraded}")
```

**Step 2: 验证模块可导入**

Run:
```bash
python -c "from core.consumers.notification_consumer import NotificationConsumer; c = NotificationConsumer(); print([t.value for t in c.message_types])"
```
Expected: 列表包含 `volatility_alert` 和 `ai_briefing`。

**Step 3: 提交（可选）**

```bash
git add core/consumers/notification_consumer.py
git commit -m "feat(notify): subscribe AI_BRIEFING and push via send_markdown"
```

---

## Task 11: 在 `app_producer_consumer.py` 注册 `x_briefing` + 启用 AI consumer

**Files:**
- Modify: `app_producer_consumer.py`
- Modify: `config/settings.py`（在 `PRODUCER_SCHEDULE` 加一项，便于将来对齐其他 producer，但本期 trigger 由 `XBriefingProducer.create_trigger()` 直接读 `SOCIAL_CONFIG`，schedule 仅作占位/文档）

**Step 1: `config/settings.py` 增加占位**

在 `PRODUCER_SCHEDULE` 末尾追加：
```python
    'x_briefing': {
        'type': 'cron',
        # 实际触发器由 XBriefingProducer.create_trigger() 读 SOCIAL_CONFIG['cron_hours']；
        # 此处保留是为了与其他 producer 在文档/排查上风格一致。
        'kwargs': {'hour': '8,20', 'minute': 0},
    },
```

**Step 2: `app_producer_consumer.py` 注册 + 启用 AI consumer**

修改三处：

(a) 顶部 import 处增加：
```python
from core.producers.x_briefing_producer import XBriefingProducer
from core.consumers.ai_briefing_consumer import AIBriefingConsumer
from config.social import SOCIAL_CONFIG, assert_social_env_ready
```

(b) `PRODUCER_REGISTRY` 加一项：
```python
PRODUCER_REGISTRY: dict[str, type] = {
    "astock":         AStockProducer,
    "usstock_minute": USStockMinuteProducer,
    "usstock_daily":  USStockDailyProducer,
    "usstock_weekly": USStockWeeklyProducer,
    "crypto":         CryptoProducer,
    "x_briefing":     XBriefingProducer,
}
```

(c) `setup_producers` 末尾、`setup_consumers` 内分别加 enabled 判断：

```python
    def setup_producers(self, producer_keys, run_immediately=True, ignore_schedule=False):
        # 如果 x_briefing 在请求列表里但 SOCIAL_CONFIG.enabled=False，丢弃并 warn
        if "x_briefing" in producer_keys and not SOCIAL_CONFIG["enabled"]:
            logging.warning(
                "[App] SOCIAL_CONFIG.enabled=False，已从启动列表中剔除 x_briefing"
            )
            producer_keys = [k for k in producer_keys if k != "x_briefing"]
        # 若 x_briefing 启用，做启动期 fail-fast 检查（缺 env / 空白名单）
        if "x_briefing" in producer_keys:
            assert_social_env_ready()

        extra_kwargs = {
            "usstock_minute": {"interval_minutes": 5},
        }
        for key in producer_keys:
            cls = PRODUCER_REGISTRY[key]
            kwargs = {
                "run_immediately": run_immediately,
                "ignore_schedule": ignore_schedule,
                **extra_kwargs.get(key, {}),
            }
            self.producers.append(cls(**kwargs))
        logging.info(f"已启用 producer: {producer_keys}")
        print(f"生产者设置完成: {producer_keys}")

    def setup_consumers(self):
        self.consumers.append(StorageConsumer())
        self.consumers.append(VolatilityConsumer())
        self.consumers.append(NotificationConsumer())
        if SOCIAL_CONFIG["enabled"]:
            self.consumers.append(AIBriefingConsumer())
            logging.info("[App] AIBriefingConsumer 已启用")
        else:
            logging.info("[App] SOCIAL_CONFIG.enabled=False，AIBriefingConsumer 跳过")
        print("消费者设置完成")
```

**Step 3: 验证 `--list-producers` 包含 `x_briefing`**

Run:
```bash
python app_producer_consumer.py --list-producers
```
Expected: 输出列表里有 `x_briefing -> XBriefingProducer`。

**Step 4: 验证 enabled=False 时启动跳过（手工）**

临时把 `SOCIAL_CONFIG["enabled"]` 改为 `False`，跑：
```bash
python app_producer_consumer.py --producers x_briefing --once
```
Expected: 日志里出现 `已从启动列表中剔除 x_briefing` 和 `AIBriefingConsumer 跳过`，进程退出（因为没有别的 producer 跑）。
随后改回 `True`。

**Step 5: 提交（可选）**

```bash
git add app_producer_consumer.py config/settings.py
git commit -m "feat(app): register x_briefing producer and gate AI consumer by SOCIAL_CONFIG.enabled"
```

---

## Task 12: 文档与环境变量

**Files:**
- Modify: `README.md`（在"扩展"或"运行"附近增加 X 简报章节）
- Modify/Create: `.env`（用户私有，本步只在文档中写明应包含哪些 key）

**Step 1: 给 README 加章节**

在 `README.md` 现有"运行"章节之后追加：

```markdown
## X 推文 AI 简报

每天 cron 触发 1–2 次，从配置的白名单账号拉取增量推文，调用 LLM 生成 markdown 简报，
通过现有企微 webhook 推送，原始推文与简报均落 SQLite。

启动：
```bash
# 单独跑
python app_producer_consumer.py --producers x_briefing
# 与行情 producer 一起跑
python app_producer_consumer.py --producers crypto,usstock_daily,x_briefing
# 立即跑一次（用于联调；since_id 已更新后再跑会拿到 0 条 → 不重复推送）
python app_producer_consumer.py --producers x_briefing --once
```

环境变量（追加到 `.env`）：
```env
SOCIALDATA_API_KEY=...           # 第三方 X 聚合服务的 key
ANTHROPIC_API_KEY=...            # Claude API key
```

主要配置项位于 `config/social.py`：
- `enabled`：总开关
- `whitelist`：关注的 X 账号（不带 @）
- `cron_hours`：简报时段，例 `"8,20"`
- `prompt_template` / `user_prompt_extra`：可调
- `social_provider` / `llm_provider`：服务与模型选择

数据落地：
- `social_posts`：推文，`post_id` 唯一
- `briefings`：每次简报，`degraded=true` 表示 LLM 失败时的降级简报
```

**Step 2: 写 `.env` 模板提示（用户自行写入私有 `.env`）**

如果项目目前没有 `.env.example`，本步**不**新建——避免污染；只在 README 里给出 key 示例（已在 Step 1 完成）。

**Step 3: 提交（可选）**

```bash
git add README.md
git commit -m "docs: document X AI briefing pipeline and required env vars"
```

---

## Task 13: 端到端手工 Dry-run

**目的**：在不写自动化测试的前提下，验证整条链路能跑通。

**前置**：
- `.env` 已配置 `SOCIALDATA_API_KEY` / `ANTHROPIC_API_KEY` / `WECOM_WEBHOOK_URL`
- `SOCIAL_CONFIG["whitelist"]` 至少有 1 个公开账号（建议先放 1 个低频账号，避免拉太多）
- Redis 本地可启动（`redis-server` 安装就绪）

**Step 1: 起一次 `--once`**

Run:
```bash
python app_producer_consumer.py --producers x_briefing --once
```

**Step 2: 观察日志，逐项核对**

Expected（关键行）:
- `[XBriefingProducer] APScheduler 生产者已启动` 或 `忽略调度设置`
- `[SocialDataClient] fetch @<handle> since=None → N posts in XXXms`
- 至少一条 `[XBriefingProducer] 生产任务完成，生成 1 条消息` （或 0 条 → "no new posts, skip publishing"，则改个新账号或清表后重试）
- `[StorageConsumer] social_posts batch saved: new=N total_in_batch=N`
- `[AnthropicLLMClient] model=claude-... in=XXX out=XXX elapsed=XXXms`
- `[AIBriefingConsumer] published AI_BRIEFING degraded=False posts=N`
- `[StorageConsumer] briefing saved id=1 degraded=False`
- `[WeChatNotifier] markdown 发送成功，长度=XXX`
- `[NotificationConsumer] AI 简报推送成功 degraded=False`

**Step 3: 检查 SQLite**

Run:
```bash
sqlite3 market_data.db "SELECT count(*) FROM social_posts;"
sqlite3 market_data.db "SELECT id, length(markdown), degraded, model, input_tokens, output_tokens FROM briefings ORDER BY id DESC LIMIT 1;"
```
Expected: `social_posts` count > 0；`briefings` 最新一行 `degraded=0` 且 `length(markdown) > 0`。

**Step 4: 验证幂等（再跑一次）**

Run:
```bash
python app_producer_consumer.py --producers x_briefing --once
```
Expected: 日志出现 `[XBriefingProducer] no new posts, skip publishing`；`briefings` 表行数不变；企微无新消息。

**Step 5: 验证 LLM 失败的降级路径（手工破坏 key）**

临时 `export ANTHROPIC_API_KEY=invalid` 后再跑（先清掉对应账号最新一条以制造新数据，例如手工删一行：`sqlite3 market_data.db "DELETE FROM social_posts WHERE post_id=(SELECT max(post_id) FROM social_posts);"`）：
```bash
python app_producer_consumer.py --producers x_briefing --once
```
Expected:
- 日志 `LLM summarize failed: ...`
- `[AIBriefingConsumer] published AI_BRIEFING degraded=True posts=N`
- 企微收到一条"📰 AI 简报生成失败..."的消息
- `briefings` 新增一行 `degraded=1`

恢复 `ANTHROPIC_API_KEY` 后再跑一次确认恢复正常。

**Step 6: 与行情 producer 共跑（冒烟）**

Run:
```bash
python app_producer_consumer.py --producers crypto,x_briefing --no-immediate
```
（不传 `--once`，让两个 producer 都按各自 cron 等待。观察启动日志确认两条链路都注册成功。）
Ctrl+C 退出。

**Step 7: 提交（可选）**

通常 Dry-run 不产生新代码改动；如果中途修了什么再单独 commit。

---

## 完成判定（DoD）

- [x] `python app_producer_consumer.py --list-producers` 能看到 `x_briefing`
- [x] 单跑 `--producers x_briefing --once` 走完一次后：`social_posts` 有新行、`briefings` 有 `degraded=0` 的新行、企微收到 markdown
- [x] 第二次 `--once` 不重复推送（since_id 闭环）
- [x] LLM 失败时走降级路径，企微仍收到一条"失败"提示
- [x] 与现有行情 producer 共跑无冲突
- [x] `SOCIAL_CONFIG["enabled"] = False` 时 producer 与 AI consumer 都不实例化

---

## 后续（不在本期做，仅备忘）

- 自动化测试覆盖（单元 + 集成 + E2E）
- LLM 输出强制 JSON / 结构化 sections，便于在企微做"分主题分组"渲染
- 多渠道分发（Telegram、邮件）
- Pub/Sub → Streams 迁移（出现"丢一条贵"场景时）
- 配置分文件（`config/market.py` 拆出去）
- `MessageType` 老命名加业务前缀
