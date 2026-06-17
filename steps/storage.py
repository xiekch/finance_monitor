import json
import logging
from typing import Any

from steps.base import Step
from models.messages import BaseMessage, MessageType, PriceDataMessage, SocialPostBatchMessage, AIBriefingMessage
from models.market import PriceData
from models.social import SocialPost, Briefing
from storage.market_db import MarketDataDB
from storage.social_store import SocialPostStore
from utils.time_util import utc_now_iso


class StorageStep(Step):
    """透传存储：根据数据类型分发存储，处理完后原样返回 data。"""

    def __init__(
        self,
        market_db: MarketDataDB | None = None,
        social_store: SocialPostStore | None = None,
    ):
        self.name = "StorageStep"
        self.market_db = market_db or MarketDataDB()
        self.social_store = social_store or SocialPostStore()

    async def process(self, data: Any) -> Any:
        if data is None:
            return None

        if isinstance(data, list):
            for item in data:
                self._store_one(item)
        else:
            self._store_one(data)

        return data

    def _store_one(self, item: Any):
        if isinstance(item, PriceDataMessage):
            self._store_price(item)
        elif isinstance(item, SocialPostBatchMessage):
            self._store_social_batch(item)
        elif isinstance(item, AIBriefingMessage):
            self._store_briefing(item)
        elif isinstance(item, BaseMessage):
            mt = item.message_type
            if mt in (MessageType.PRICE_DATA, MessageType.HISTORICAL_PRICE_DATA):
                self._store_price(item)
            elif mt == MessageType.SOCIAL_POST_BATCH:
                self._store_social_batch(item)
            elif mt == MessageType.AI_BRIEFING:
                self._store_briefing(item)

    def _store_price(self, message: BaseMessage):
        price_data = PriceData.from_dict(message.payload)
        if self.market_db.save_price_data(price_data):
            logging.info(f"[{self.name}] 数据已保存: {price_data.symbol}")
        else:
            logging.info(f"[{self.name}] 数据已存在: {price_data.symbol}")

    def _store_social_batch(self, message: BaseMessage):
        posts = [SocialPost.from_dict(p) for p in message.payload.get("posts", [])]
        n = self.social_store.save_posts(posts)
        logging.info(f"[{self.name}] social_posts saved: new={n} total={len(posts)}")

    def _store_briefing(self, message: BaseMessage):
        p = message.payload
        briefing = Briefing(
            created_at=p.get("created_at") or utc_now_iso(),
            window_hours=p.get("window_hours", 0),
            source_post_ids=p.get("source_post_ids", []),
            markdown=p.get("markdown", ""),
            sections_json=json.dumps(p.get("sections", [])),
            model=(p.get("stats") or {}).get("model", ""),
            input_tokens=(p.get("stats") or {}).get("input_tokens", 0),
            output_tokens=(p.get("stats") or {}).get("output_tokens", 0),
            degraded=bool(p.get("degraded", False)),
            error=p.get("error"),
            source=message.source or "",
        )
        bid = self.social_store.save_briefing(briefing)
        logging.info(f"[{self.name}] briefing saved id={bid} degraded={briefing.degraded}")
