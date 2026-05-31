import logging
from collections import Counter
from dataclasses import asdict
from typing import Sequence, List, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.base import BaseTrigger

from core.producers.base_producer import BaseProducer
from core.message_types import BaseMessage, SocialPostBatchMessage
from core.clients.social_client import SocialClient, build_default_social_client
from models.social_data import SocialPostStore, SocialPost
from config.social import SOCIAL_CONFIG


class XBriefingProducer(BaseProducer):
    """每天 cron 触发，从白名单账号增量拉取 X 推文，发布 SOCIAL_POST_BATCH。

    调度优先级：构造时显式注入的 ``trigger`` > 从 SOCIAL_CONFIG['cron_hours'] 派生的 CronTrigger。
    """

    def __init__(
        self,
        social: Optional[SocialClient] = None,
        store: Optional[SocialPostStore] = None,
        trigger: Optional[BaseTrigger] = None,
        run_immediately: bool = False,
        ignore_schedule: bool = False,
    ):
        if trigger is None and not ignore_schedule:
            trigger = CronTrigger(hour=SOCIAL_CONFIG["cron_hours"], minute=0)
        super().__init__(
            "XBriefingProducer",
            trigger=trigger,
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
        )
        self.social = social or build_default_social_client()
        self.store = store or SocialPostStore()

    async def produce_data(self) -> Sequence[BaseMessage]:
        whitelist: List[str] = SOCIAL_CONFIG["whitelist"]
        limit: int = SOCIAL_CONFIG["fetch_limit_per_user"]
        all_new: List[SocialPost] = []

        for handle in whitelist:
            since_id = self.store.get_latest_post_id(handle)
            try:
                posts = await self.social.fetch_user_timeline(handle, since_id, limit)
            except Exception as e:
                logging.warning(f"[XBriefingProducer] @{handle} fetch failed, skip: {e}")
                continue
            all_new.extend(posts)

        if not all_new:
            logging.info("[XBriefingProducer] no new posts, skip publishing")
            return []

        payload = {
            "posts": [asdict(p) for p in all_new],
            "window_hours": SOCIAL_CONFIG["window_hours"],
            "stats": {
                "total": len(all_new),
                "by_author": dict(Counter(p.author for p in all_new)),
            },
        }
        return [SocialPostBatchMessage(payload=payload, source=self.producer_name)]
