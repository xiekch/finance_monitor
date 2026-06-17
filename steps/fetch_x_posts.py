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

        all_new: List[SocialPost] = []
        since = window_since(window_hours)
        if fetch_mode == "search":
            query = " OR ".join(f"from:{h}" for h in whitelist)
            try:
                search_limit = SOCIAL_CONFIG["social_provider"].get("search_limit", 40)
                all_new = await self.social.search_tweets(query, limit=search_limit, since=since)
            except Exception as e:
                logging.error(f"[{self.name}] advanced_search failed: {e}", exc_info=True)
        else:
            limit: int = SOCIAL_CONFIG["fetch_limit_per_user"]
            for handle in whitelist:
                since_id = self.store.get_latest_post_id(handle, platform="x")
                try:
                    posts = await self.social.fetch_user_timeline(handle, since_id, limit)
                except Exception as e:
                    logging.warning(f"[{self.name}] @{handle} fetch failed, skip: {e}")
                    continue
                all_new.extend(posts)

        db_posts = self.store.get_posts_since(since, platform="x")

        seen_ids: set[str] = set()
        merged: List[SocialPost] = []
        for p in list(all_new) + db_posts:
            if p.post_id in seen_ids:
                continue
            seen_ids.add(p.post_id)
            merged.append(p)
        merged.sort(key=lambda p: p.created_at)

        if not merged:
            logging.info(f"[{self.name}] no new posts and no db history, skip")
            return None

        by_author = dict(Counter(p.author for p in merged))
        logging.info(
            f"[{self.name}] batch ready: {len(merged)} posts "
            f"(new={len(all_new)}, db={len(db_posts)}, deduped={len(merged)}), "
            f"by_author={by_author}"
        )

        payload = {
            "posts": [asdict(p) for p in merged],
            "platform": "x",
            "window_hours": window_hours,
            "stats": {"total": len(merged), "new": len(all_new), "by_author": by_author},
        }
        return SocialPostBatchMessage(payload=payload, source=self.name)
