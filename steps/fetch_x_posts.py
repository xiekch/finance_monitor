import logging
from collections import Counter
from dataclasses import asdict
from typing import Any, List

from steps.base import Step
from models.messages import SocialPostBatchMessage
from clients.social_client import SocialClient, build_default_social_client
from storage.social_store import SocialPostStore
from config.social import SOCIAL_CONFIG


class FetchXPosts(Step):

    def __init__(
        self,
        social: SocialClient | None = None,
        store: SocialPostStore | None = None,
    ):
        self.name = "FetchXPosts"
        self.social = social or build_default_social_client()
        self.store = store or SocialPostStore()

    async def process(self, data: Any = None) -> SocialPostBatchMessage | None:
        whitelist: List[str] = SOCIAL_CONFIG["whitelist"]
        limit: int = SOCIAL_CONFIG["fetch_limit_per_user"]
        all_new = []

        for handle in whitelist:
            since_id = self.store.get_latest_post_id(handle, platform="x")
            try:
                posts = await self.social.fetch_user_timeline(handle, since_id, limit)
            except Exception as e:
                logging.warning(f"[{self.name}] @{handle} fetch failed, skip: {e}")
                continue
            all_new.extend(posts)

        if not all_new:
            logging.info(f"[{self.name}] no new posts, skip")
            return None

        by_author = dict(Counter(p.author for p in all_new))
        logging.info(f"[{self.name}] batch ready: {len(all_new)} posts, by_author={by_author}")

        payload = {
            "posts": [asdict(p) for p in all_new],
            "platform": "x",
            "window_hours": SOCIAL_CONFIG["window_hours"],
            "stats": {"total": len(all_new), "by_author": by_author},
        }
        return SocialPostBatchMessage(payload=payload, source=self.name)
