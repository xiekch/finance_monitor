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
