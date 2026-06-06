import logging
from collections import Counter
from dataclasses import asdict
from typing import Sequence, List, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.base import BaseTrigger

from producers.base_producer import BaseProducer
from models.messages import BaseMessage, SocialPostBatchMessage
from clients.weibo_client import WeiboClient, build_default_weibo_client
from models.social import SocialPost
from storage.social_store import SocialPostStore
from config.social import SOCIAL_CONFIG


class WeiboBriefingProducer(BaseProducer):
    """从白名单微博账号增量拉取动态，发布 SOCIAL_POST_BATCH。"""

    def __init__(
        self,
        weibo: Optional[WeiboClient] = None,
        store: Optional[SocialPostStore] = None,
        trigger: Optional[BaseTrigger] = None,
        run_immediately: bool = False,
        ignore_schedule: bool = False,
    ):
        if trigger is None and not ignore_schedule:
            trigger = CronTrigger(
                hour=SOCIAL_CONFIG["cron_hours"],
                minute=SOCIAL_CONFIG.get("cron_minute", 0),
            )
        super().__init__(
            "WeiboBriefingProducer",
            trigger=trigger,
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
        )
        self.weibo = weibo or build_default_weibo_client()
        self.store = store or SocialPostStore()

    async def produce_data(self) -> Sequence[BaseMessage]:
        whitelist: List[str] = SOCIAL_CONFIG.get("weibo_whitelist", [])
        limit: int = SOCIAL_CONFIG.get("weibo_fetch_limit_per_user",
                                       SOCIAL_CONFIG["fetch_limit_per_user"])
        all_new: List[SocialPost] = []

        for uid in whitelist:
            since_id = self.store.get_latest_post_id(uid, platform="weibo")
            try:
                posts = await self.weibo.fetch_user_timeline(uid, since_id, limit)
            except Exception as e:
                logging.warning(
                    f"[WeiboBriefingProducer] uid={uid} fetch failed, skip: {e}"
                )
                continue
            all_new.extend(posts)

        if not all_new:
            logging.info("[WeiboBriefingProducer] no new posts, skip publishing")
            return []

        by_author = dict(Counter(p.author for p in all_new))
        logging.info(
            f"[WeiboBriefingProducer] batch ready: {len(all_new)} posts, "
            f"by_author={by_author}"
        )

        payload = {
            "posts": [asdict(p) for p in all_new],
            "platform": "weibo",
            "window_hours": SOCIAL_CONFIG["window_hours"],
            "stats": {
                "total": len(all_new),
                "by_author": by_author,
            },
        }
        return [SocialPostBatchMessage(payload=payload, source=self.producer_name)]
