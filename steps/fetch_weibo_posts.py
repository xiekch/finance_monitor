import logging
from collections import Counter
from dataclasses import asdict
from typing import Any, List

from steps.base import Step
from models.messages import SocialPostBatchMessage
from clients.weibo_client import WeiboClient, build_default_weibo_client
from storage.social_store import SocialPostStore
from config.social import SOCIAL_CONFIG


class FetchWeiboPosts(Step):

    def __init__(
        self,
        weibo: WeiboClient | None = None,
        store: SocialPostStore | None = None,
    ):
        self.name = "FetchWeiboPosts"
        self.weibo = weibo or build_default_weibo_client()
        self.store = store or SocialPostStore()

    async def process(self, data: Any = None) -> SocialPostBatchMessage | None:
        whitelist: List[str] = SOCIAL_CONFIG.get("weibo_whitelist", [])
        limit: int = SOCIAL_CONFIG.get(
            "weibo_fetch_limit_per_user", SOCIAL_CONFIG["fetch_limit_per_user"]
        )
        all_new = []

        for uid in whitelist:
            since_id = self.store.get_latest_post_id(uid, platform="weibo")
            try:
                posts = await self.weibo.fetch_user_timeline(uid, since_id, limit)
            except Exception as e:
                logging.warning(f"[{self.name}] uid={uid} fetch failed, skip: {e}")
                continue
            all_new.extend(posts)

        if not all_new:
            logging.info(f"[{self.name}] no new posts, skip")
            return None

        by_author = dict(Counter(p.author for p in all_new))
        logging.info(f"[{self.name}] batch ready: {len(all_new)} posts, by_author={by_author}")

        payload = {
            "posts": [asdict(p) for p in all_new],
            "platform": "weibo",
            "window_hours": SOCIAL_CONFIG["window_hours"],
            "stats": {"total": len(all_new), "by_author": by_author},
        }
        return SocialPostBatchMessage(payload=payload, source=self.name)
