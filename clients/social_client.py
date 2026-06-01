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
    """twitterapi.io 适配。

    特点：
    - Header 用 X-API-Key（不是 Bearer）
    - last_tweets 不支持 since_id，拉最近 N 条后 client-side 按 id 过滤
    - free tier 限速 1 req / 5 sec，单个 cron 多账号时会被节流（重试足够慢即可）
    """

    def __init__(self, api_key: str, base_url: str, timeout_sec: int = 10):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_sec
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key,
            "Accept": "application/json",
        })

    async def fetch_user_timeline(
        self, handle: str, since_id: Optional[str], limit: int
    ) -> List[SocialPost]:
        url = f"{self.base_url}/twitter/user/last_tweets"
        params = {"userName": handle, "count": limit}

        last_err: Optional[Exception] = None
        for attempt in range(2):
            t0 = time.time()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("status") != "success":
                    raise RuntimeError(
                        f"api error: {payload.get('msg') or payload.get('message') or payload}"
                    )
                tweets = (payload.get("data") or {}).get("tweets") or []
                # twitterapi.io 不支持 since_id，client-side 按 snowflake id 过滤
                if since_id:
                    try:
                        cutoff = int(since_id)
                        tweets = [t for t in tweets if int(t["id"]) > cutoff]
                    except (ValueError, TypeError, KeyError):
                        pass
                posts = [self._parse(t) for t in tweets]
                ms = int((time.time() - t0) * 1000)
                logging.info(
                    f"[TwitterApiIoClient] fetch @{handle} since={since_id} → {len(posts)} posts in {ms}ms"
                )
                return posts
            except Exception as e:
                last_err = e
                wait = 0.5 * (2 ** attempt)
                logging.warning(
                    f"[TwitterApiIoClient] fetch @{handle} attempt {attempt + 1} failed: {e}; retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"fetch_user_timeline @{handle} failed: {last_err}")

    @staticmethod
    def _parse(t: dict) -> SocialPost:
        raw_dt = t.get("createdAt", "")
        try:
            # twitterapi.io 返回 "Mon Jun 01 04:58:38 +0000 2026" 格式
            iso_dt = datetime.strptime(raw_dt, "%a %b %d %H:%M:%S %z %Y").isoformat()
        except (ValueError, TypeError):
            iso_dt = raw_dt
        author = t.get("author") or {}
        return SocialPost(
            post_id=str(t.get("id", "")),
            author=author.get("userName", ""),
            author_name=author.get("name", ""),
            text=t.get("text") or "",
            created_at=iso_dt,
            url=t.get("url") or t.get("twitterUrl") or "",
            is_retweet=False,
            referenced_url=None,
        )


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
    return cls(
        api_key=os.getenv(cfg["api_key_env"], ""),
        base_url=cfg["base_url"],
        timeout_sec=cfg["timeout_sec"],
    )
