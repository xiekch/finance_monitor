import logging
from collections import Counter
from dataclasses import asdict
from typing import Any, List

from steps.base import Step
from models.messages import SocialPostBatchMessage
from models.social import SocialPost
from clients.social_client import SocialClient, build_default_social_client
from storage.social_store import SocialPostStore
from config.social import SOCIAL_CONFIG
from utils.time_util import window_since


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
        window_hours: int = SOCIAL_CONFIG["window_hours"]
        fetch_mode: str = SOCIAL_CONFIG["social_provider"].get("fetch_mode", "timeline")

        posts: List[SocialPost] = []
        if fetch_mode == "search":
            query = " OR ".join(f"from:{h}" for h in whitelist)
            try:
                since = window_since(window_hours)
                search_limit = SOCIAL_CONFIG["social_provider"].get("search_limit", 40)
                posts = await self.social.search_tweets(
                    query, limit=search_limit, since=since,
                )
            except Exception as e:
                logging.error(f"[{self.name}] advanced_search failed: {e}", exc_info=True)
        else:
            limit: int = SOCIAL_CONFIG["fetch_limit_per_user"]
            for handle in whitelist:
                since_id = self.store.get_latest_post_id(handle, platform="x")
                try:
                    fetched = await self.social.fetch_user_timeline(handle, since_id, limit)
                except Exception as e:
                    logging.warning(f"[{self.name}] @{handle} fetch failed, skip: {e}")
                    continue
                posts.extend(fetched)

        if not posts:
            logging.info(f"[{self.name}] no posts, skip")
            return None

        posts.sort(key=lambda p: p.created_at)
        by_author = dict(Counter(p.author for p in posts))
        logging.info(
            f"[{self.name}] batch ready: {len(posts)} posts, by_author={by_author}"
        )

        payload = {
            "posts": [asdict(p) for p in posts],
            "platform": "x",
            "window_hours": window_hours,
            "stats": {"total": len(posts), "new": len(posts), "by_author": by_author},
        }
        return SocialPostBatchMessage(payload=payload, source=self.name)
