"""X 推文抓取边界。业务代码只依赖 SocialClient 协议。"""
import logging
import time
from datetime import datetime
from typing import List, Optional, Protocol

import requests

from models.social import SocialPost


class SocialClient(Protocol):
    async def fetch_user_timeline(
        self, handle: str, since_id: Optional[str], limit: int
    ) -> List[SocialPost]: ...


class SocialDataClient:
    """socialdata.tools 风格 HTTP API 适配。"""

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
                for p in posts:
                    snippet = p.text.replace("\n", " ")[:120]
                    suffix = "..." if len(p.text) > 120 else ""
                    rt = " [RT]" if p.is_retweet else ""
                    logging.info(f"  └ [{p.post_id}]{rt} {snippet}{suffix}")
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


class TwitterApiIoClient:
    """twitterapi.io 适配（last_tweets endpoint）。

    特点：
    - Header 用 X-API-Key（不是 Bearer）
    - 不支持 count；每页固定最多 20 条，通过 cursor 翻页
    - 不支持 since_id；client-side 按 snowflake id 过滤
    - free tier 限速 1 req / 5 sec，多页时主动 sleep 间隔
    - includeReplies 默认 false；要拿回复推文需显式开启
    """

    _PAGE_SIZE = 20             # twitterapi.io last_tweets 服务端定的
    _RATE_LIMIT_SLEEP = 5.5     # free tier 1 req / 5 sec 节流

    def __init__(self, api_key: str, base_url: str, timeout_sec: int = 10,
                 include_replies: bool = False):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_sec
        self.include_replies = include_replies
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key,
            "Accept": "application/json",
        })

    async def fetch_user_timeline(
        self, handle: str, since_id: Optional[str], limit: int
    ) -> List[SocialPost]:
        url = f"{self.base_url}/twitter/user/last_tweets"
        out: List[SocialPost] = []
        cursor = ""
        page = 0
        # 上限：limit 对应的页数 + 1 页冗余，再封顶 10 页（200 条）防止异常无限翻
        page_cap = min(10, (limit + self._PAGE_SIZE - 1) // self._PAGE_SIZE + 1)
        cutoff = int(since_id) if since_id and since_id.isdigit() else None

        while len(out) < limit and page < page_cap:
            if page > 0:
                # 翻第二页起主动 sleep 满足 free tier 速率
                time.sleep(self._RATE_LIMIT_SLEEP)

            params: dict = {"userName": handle, "cursor": cursor}
            if self.include_replies:
                params["includeReplies"] = "true"
            payload = self._get_with_retry(url, params, f"@{handle} page {page + 1}")

            tweets = (payload.get("data") or {}).get("tweets") or []
            hit_boundary = False
            if cutoff is not None:
                fresh = []
                for t in tweets:
                    try:
                        if int(t["id"]) > cutoff:
                            fresh.append(t)
                        else:
                            hit_boundary = True
                    except (ValueError, TypeError, KeyError):
                        fresh.append(t)
                tweets = fresh

            out.extend(self._parse(t) for t in tweets)
            cursor = payload.get("next_cursor") or ""
            has_next = bool(payload.get("has_next_page"))
            page += 1

            logging.info(
                f"[TwitterApiIoClient] fetch @{handle} page {page} +{len(tweets)} "
                f"(total {len(out)}/{limit} has_next={has_next} hit_seen={hit_boundary})"
            )

            if not has_next or hit_boundary:
                break

        result = out[:limit]
        for p in result:
            snippet = p.text.replace("\n", " ")[:120]
            suffix = "..." if len(p.text) > 120 else ""
            rt = " [RT]" if p.is_retweet else ""
            logging.info(f"  └ [{p.post_id}]{rt} {snippet}{suffix}")
        return result

    def _get_with_retry(self, url: str, params: dict, label: str) -> dict:
        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("status") != "success":
                    raise RuntimeError(
                        f"api error: {payload.get('msg') or payload.get('message') or payload}"
                    )
                return payload
            except Exception as e:
                last_err = e
                wait = 0.5 * (2 ** attempt)
                logging.warning(
                    f"[TwitterApiIoClient] {label} attempt {attempt + 1} failed: {e}; retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"{label} failed: {last_err}")

    @staticmethod
    def _parse(t: dict) -> SocialPost:
        raw_dt = t.get("createdAt", "")
        try:
            # twitterapi.io 返回 "Mon Jun 01 04:58:38 +0000 2026" 格式
            iso_dt = datetime.strptime(raw_dt, "%a %b %d %H:%M:%S %z %Y").isoformat()
        except (ValueError, TypeError):
            iso_dt = raw_dt
        author = t.get("author") or {}
        # 拼接引用 / 转推的原文上下文，否则 LLM 只看到 "True/Yes/RT @x: 截断..." 抓不到信息
        text, is_retweet, referenced_url = _compose_text_with_context(t)
        return SocialPost(
            post_id=str(t.get("id", "")),
            author=author.get("userName", ""),
            author_name=author.get("name", ""),
            text=text,
            created_at=iso_dt,
            url=t.get("url") or t.get("twitterUrl") or "",
            is_retweet=is_retweet,
            referenced_url=referenced_url,
        )


def _compose_text_with_context(t: dict) -> tuple[str, bool, Optional[str]]:
    """从 twitterapi.io 的单条 tweet 还原 LLM 需要的完整 text。

    返回 (text, is_retweet, referenced_url)。三种情况：
    - 转推（retweeted_tweet 非空）：顶层 text 是 "RT @x: 截断..."，
      用原推文完整 text 重组
    - 引用（quoted_tweet 非空，纯粹是 Musk 那种"True/Yes/Bullseye" 加
      被引用原文）：在顶层 text 后附 "> @作者: 完整内容"
    - 普通推文：直接用顶层 text
    """
    raw_text = t.get("text") or ""
    retweeted = t.get("retweeted_tweet")
    quoted = t.get("quoted_tweet")

    if retweeted:
        rt_author = (retweeted.get("author") or {}).get("userName", "")
        rt_text = retweeted.get("text") or ""
        text = f"RT @{rt_author}: {rt_text}"
        ref_url = retweeted.get("url") or retweeted.get("twitterUrl")
        return text, True, ref_url

    if quoted:
        q_author = (quoted.get("author") or {}).get("userName", "")
        q_text = quoted.get("text") or ""
        text = f"{raw_text}\n\n> @{q_author}: {q_text}"
        ref_url = quoted.get("url") or quoted.get("twitterUrl")
        return text, False, ref_url

    return raw_text, False, None


_CLIENT_CLASSES = {
    "socialdata": SocialDataClient,
    "twitterapi_io": TwitterApiIoClient,
}


def build_default_social_client() -> SocialClient:
    import os
    from config.social import SOCIAL_CONFIG
    cfg = SOCIAL_CONFIG["social_provider"]
    name = cfg["name"]
    try:
        cls = _CLIENT_CLASSES[name]
    except KeyError as e:
        raise ValueError(
            f"未知 social_provider.name: {name!r}; 可选: {sorted(_CLIENT_CLASSES)}"
        ) from e
    kwargs = dict(
        api_key=os.getenv(cfg["api_key_env"], ""),
        base_url=cfg["base_url"],
        timeout_sec=cfg["timeout_sec"],
    )
    if cls is TwitterApiIoClient:
        kwargs["include_replies"] = bool(cfg.get("include_replies", False))
    return cls(**kwargs)
