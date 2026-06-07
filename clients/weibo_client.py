"""微博数据抓取边界。使用官方 API (open.weibo.com)。"""
import logging
import re
import time
from datetime import datetime
from typing import List, Optional

import requests

from models.social import SocialPost


class WeiboClient:
    """微博官方 API 适配。

    - GET /2/statuses/user_timeline.json 拉用户时间线
    - access_token 通过 query param 传递
    - count 最大 100，支持 since_id 增量
    - 返回格式 {"statuses": [...], "total_number": N}
    """

    _MAX_COUNT = 100
    _RATE_LIMIT_SLEEP = 1.0

    def __init__(self, access_token: str, base_url: str = "https://api.weibo.com/2",
                 timeout_sec: int = 10):
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_sec
        self.session = requests.Session()

    async def fetch_user_timeline(
        self, uid: str, since_id: Optional[str], limit: int
    ) -> List[SocialPost]:
        """拉取用户最新微博。

        Args:
            uid: 微博用户 UID（数字字符串）
            since_id: 上次拉取的最大 post_id，增量拉取用
            limit: 本次最多拉取条数
        """
        url = f"{self.base_url}/statuses/user_timeline.json"
        out: List[SocialPost] = []
        page = 1
        page_cap = max(1, (limit + self._MAX_COUNT - 1) // self._MAX_COUNT + 1)

        while len(out) < limit and page <= page_cap:
            if page > 1:
                time.sleep(self._RATE_LIMIT_SLEEP)

            params = {
                "access_token": self.access_token,
                "uid": uid,
                "count": min(self._MAX_COUNT, limit - len(out)),
                "page": page,
            }
            if since_id:
                params["since_id"] = since_id

            payload = self._get_with_retry(url, params, f"uid={uid} page {page}")
            statuses = payload.get("statuses") or []

            if not statuses:
                break

            for s in statuses:
                out.append(self._parse(s))

            page += 1
            logging.info(
                f"[WeiboClient] fetch uid={uid} page {page - 1} "
                f"+{len(statuses)} (total {len(out)}/{limit})"
            )

        result = out[:limit]
        for p in result:
            snippet = p.text.replace("\n", " ")[:120]
            suffix = "..." if len(p.text) > 120 else ""
            rt = " [转发]" if p.is_retweet else ""
            logging.info(f"  └ [{p.post_id}]{rt} {snippet}{suffix}")
        return result

    def _get_with_retry(self, url: str, params: dict, label: str) -> dict:
        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                if "error_code" in payload:
                    raise RuntimeError(
                        f"weibo api error {payload.get('error_code')}: "
                        f"{payload.get('error')}"
                    )
                return payload
            except Exception as e:
                last_err = e
                wait = 0.5 * (2 ** attempt)
                logging.warning(
                    f"[WeiboClient] {label} attempt {attempt + 1} failed: {e}; "
                    f"retry in {wait}s"
                )
                time.sleep(wait)
        raise RuntimeError(f"{label} failed: {last_err}")

    @staticmethod
    def _parse(s: dict) -> SocialPost:
        raw_dt = s.get("created_at", "")
        try:
            iso_dt = datetime.strptime(
                raw_dt, "%a %b %d %H:%M:%S %z %Y"
            ).isoformat()
        except (ValueError, TypeError):
            iso_dt = raw_dt

        user = s.get("user") or {}
        uid = str(user.get("id", ""))
        screen_name = user.get("screen_name", "")

        text, is_retweet, referenced_url = _compose_weibo_text(s)

        mid = str(s.get("mid") or s.get("id") or "")
        mblogid = s.get("mblogid") or mid
        post_url = f"https://weibo.com/{uid}/{mblogid}" if uid else ""

        return SocialPost(
            post_id=str(s.get("id") or s.get("id_str") or mid),
            author=screen_name,
            author_name=user.get("name", screen_name),
            text=text,
            created_at=iso_dt,
            url=post_url,
            is_retweet=is_retweet,
            referenced_url=referenced_url,
            platform="weibo",
        )


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def _compose_weibo_text(s: dict) -> tuple[str, bool, Optional[str]]:
    """从微博 status 还原完整 text。

    返回 (text, is_retweet, referenced_url)。
    - 转发（retweeted_status 非空）：拼接 "转发 @原作者: 原文"
    - 普通：直接用 text，去 HTML 标签
    """
    raw_text = _strip_html(s.get("text") or "")
    retweeted = s.get("retweeted_status")

    if retweeted:
        rt_user = (retweeted.get("user") or {}).get("screen_name", "")
        rt_text = _strip_html(retweeted.get("text") or "")
        rt_uid = str((retweeted.get("user") or {}).get("id", ""))
        rt_mid = retweeted.get("mblogid") or str(retweeted.get("mid") or "")
        ref_url = f"https://weibo.com/{rt_uid}/{rt_mid}" if rt_uid else None
        text = f"转发 @{rt_user}: {rt_text}"
        return text, True, ref_url

    return raw_text, False, None


def build_default_weibo_client() -> WeiboClient:
    from config.social import SOCIAL_CONFIG
    cfg = SOCIAL_CONFIG["weibo_provider"]
    return WeiboClient(
        access_token=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout_sec=cfg["timeout_sec"],
    )
