"""X 推文抓取边界。业务代码只依赖 SocialClient 协议。"""
import logging
import time
from typing import List, Optional, Protocol

import requests

from models.social import SocialPost


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
