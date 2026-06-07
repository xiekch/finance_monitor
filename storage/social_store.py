"""社交帖（X / 微博）+ AI 简报的 SQLite 持久化层。复用 market_data.db。"""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import List, Optional

from config.settings import DATABASE_CONFIG
from models.social import SocialPost, Briefing


_SCHEMA_VERSION = 3

_MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS social_posts (
               post_id        TEXT PRIMARY KEY,
               author         TEXT NOT NULL,
               author_name    TEXT,
               text           TEXT NOT NULL,
               created_at     TEXT NOT NULL,
               url            TEXT,
               is_retweet     INTEGER DEFAULT 0,
               referenced_url TEXT,
               fetched_at     TEXT NOT NULL
           )""",
        """CREATE INDEX IF NOT EXISTS idx_social_posts_author_created
               ON social_posts(author, created_at DESC)""",
        """CREATE TABLE IF NOT EXISTS briefings (
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
           )""",
    ],
    2: [
        "ALTER TABLE social_posts RENAME TO _social_posts_old",

        """CREATE TABLE social_posts (
               platform       TEXT NOT NULL DEFAULT 'x',
               post_id        TEXT NOT NULL,
               author         TEXT NOT NULL,
               author_name    TEXT,
               text           TEXT NOT NULL,
               created_at     TEXT NOT NULL,
               url            TEXT,
               is_retweet     INTEGER DEFAULT 0,
               referenced_url TEXT,
               fetched_at     TEXT NOT NULL,
               PRIMARY KEY (platform, post_id)
           )""",
        """INSERT INTO social_posts
               (platform, post_id, author, author_name, text,
                created_at, url, is_retweet, referenced_url, fetched_at)
           SELECT 'x', post_id, author, author_name, text,
                  created_at, url, is_retweet, referenced_url, fetched_at
           FROM _social_posts_old""",
        "DROP TABLE _social_posts_old",
        "DROP INDEX IF EXISTS idx_social_posts_author_created",
        """CREATE INDEX IF NOT EXISTS idx_social_posts_platform_author_created
               ON social_posts(platform, author, created_at DESC)""",
    ],
    3: [
        "ALTER TABLE briefings ADD COLUMN source TEXT NOT NULL DEFAULT ''",
    ],
}


class SocialPostStore:
    """SQLite 适配层。所有方法线程安全（每次 connect/close）。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_CONFIG["path"]
        self._lock = threading.Lock()
        self._migrate()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _migrate(self):
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id      INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL
                )
            """)
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cur.fetchone()

            if row is None:
                # 全新库 or 旧库（v1 之前没有 schema_version）
                cur.execute("PRAGMA table_info(social_posts)")
                cols = {r[1] for r in cur.fetchall()}
                if cols and "platform" not in cols:
                    current = 1
                elif cols and "platform" in cols:
                    current = _SCHEMA_VERSION
                else:
                    current = 0
                cur.execute(
                    "INSERT INTO schema_version (id, version) VALUES (1, ?)",
                    (current,),
                )
            else:
                current = row[0]

            for ver in range(current + 1, _SCHEMA_VERSION + 1):
                stmts = _MIGRATIONS.get(ver, [])
                logging.info(f"[SocialPostStore] 执行迁移 v{ver} ({len(stmts)} 条语句)")
                for sql in stmts:
                    cur.execute(sql)
                cur.execute(
                    "UPDATE schema_version SET version = ? WHERE id = 1", (ver,)
                )

            conn.commit()
            logging.info(f"[SocialPostStore] schema version={_SCHEMA_VERSION}")

    def save_posts(self, posts: List[SocialPost]) -> int:
        """INSERT OR IGNORE，返回实际新增条数。"""
        if not posts:
            return 0
        now_iso = datetime.now().isoformat()
        rows = [
            (p.platform, p.post_id, p.author, p.author_name, p.text,
             p.created_at, p.url, 1 if p.is_retweet else 0,
             p.referenced_url, now_iso)
            for p in posts
        ]
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            before = conn.total_changes
            cur.executemany("""
                INSERT OR IGNORE INTO social_posts
                (platform, post_id, author, author_name, text, created_at, url,
                 is_retweet, referenced_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
            return conn.total_changes - before

    def get_latest_post_id(self, author: str, platform: str = "x") -> Optional[str]:
        """获取某作者在指定平台上最新的 post_id。

        X 的 snowflake ID 单调递增，按整数排序最稳；
        微博等其他平台 fallback 到按 created_at 取最新。
        """
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            if platform == "x":
                cur.execute("""
                    SELECT post_id FROM social_posts
                    WHERE platform = ? AND author = ?
                    ORDER BY CAST(post_id AS INTEGER) DESC
                    LIMIT 1
                """, (platform, author))
            else:
                cur.execute("""
                    SELECT post_id FROM social_posts
                    WHERE platform = ? AND author = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (platform, author))
            row = cur.fetchone()
            return row[0] if row else None

    def get_posts_since(
        self, since: datetime, platform: Optional[str] = None,
    ) -> List[SocialPost]:
        """返回 created_at >= since 的帖子，按 created_at 正序。"""
        since_iso = since.isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            if platform:
                cur.execute(
                    """SELECT platform, post_id, author, author_name, text,
                              created_at, url, is_retweet, referenced_url
                       FROM social_posts
                       WHERE platform = ? AND created_at >= ?
                       ORDER BY created_at ASC""",
                    (platform, since_iso),
                )
            else:
                cur.execute(
                    """SELECT platform, post_id, author, author_name, text,
                              created_at, url, is_retweet, referenced_url
                       FROM social_posts
                       WHERE created_at >= ?
                       ORDER BY created_at ASC""",
                    (since_iso,),
                )
            return [
                SocialPost(
                    platform=r[0], post_id=r[1], author=r[2],
                    author_name=r[3], text=r[4], created_at=r[5],
                    url=r[6], is_retweet=bool(r[7]),
                    referenced_url=r[8],
                )
                for r in cur.fetchall()
            ]

    def save_briefing(self, briefing: Briefing) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO briefings
                (created_at, window_hours, source_post_ids, markdown, sections_json,
                 model, input_tokens, output_tokens, degraded, error, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                briefing.created_at, briefing.window_hours,
                json.dumps(briefing.source_post_ids), briefing.markdown,
                briefing.sections_json, briefing.model,
                briefing.input_tokens, briefing.output_tokens,
                1 if briefing.degraded else 0, briefing.error,
                briefing.source,
            ))
            conn.commit()
            return cur.lastrowid
