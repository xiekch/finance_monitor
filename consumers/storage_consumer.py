import json
import logging
from datetime import datetime

from consumers.base_consumer import BaseConsumer
from models.messages import (
    BaseMessage,
    MessageType,
)
from models.market import PriceData
from storage.market_db import MarketDataDB
from models.social import SocialPost, Briefing
from storage.social_store import SocialPostStore


class StorageConsumer(BaseConsumer):
    """数据存储消费者：行情 + 推文 + 简报"""

    def __init__(self):
        super().__init__("StorageConsumer", [
            MessageType.PRICE_DATA,
            MessageType.HISTORICAL_PRICE_DATA,
            MessageType.SOCIAL_POST_BATCH,
            MessageType.AI_BRIEFING,
        ])
        self.db = MarketDataDB()
        self.social_store = SocialPostStore()

    def process_message(self, message: BaseMessage):
        mt = message.message_type
        if mt in (MessageType.PRICE_DATA, MessageType.HISTORICAL_PRICE_DATA):
            self._handle_price(message)
        elif mt == MessageType.SOCIAL_POST_BATCH:
            self._handle_social_batch(message)
        elif mt == MessageType.AI_BRIEFING:
            self._handle_briefing(message)

    def _handle_price(self, message: BaseMessage):
        price_data = PriceData.from_dict(message.payload)
        if self.db.save_price_data(price_data):
            logging.info(f"[{self.consumer_name}] 数据已保存: {price_data.symbol} {price_data}")
        else:
            logging.info(f"[{self.consumer_name}] 数据已存在，无需保存: {price_data.symbol} {price_data}")

    def _handle_social_batch(self, message: BaseMessage):
        posts = [SocialPost.from_dict(p) for p in message.payload.get("posts", [])]
        n = self.social_store.save_posts(posts)
        logging.info(
            f"[{self.consumer_name}] social_posts batch saved: "
            f"new={n} total_in_batch={len(posts)}"
        )

    def _handle_briefing(self, message: BaseMessage):
        p = message.payload
        briefing = Briefing(
            created_at=p.get("created_at") or datetime.now().isoformat(),
            window_hours=p.get("window_hours", 0),
            source_post_ids=p.get("source_post_ids", []),
            markdown=p.get("markdown", ""),
            sections_json=json.dumps(p.get("sections", [])),
            model=(p.get("stats") or {}).get("model", ""),
            input_tokens=(p.get("stats") or {}).get("input_tokens", 0),
            output_tokens=(p.get("stats") or {}).get("output_tokens", 0),
            degraded=bool(p.get("degraded", False)),
            error=p.get("error"),
        )
        bid = self.social_store.save_briefing(briefing)
        logging.info(
            f"[{self.consumer_name}] briefing saved id={bid} degraded={briefing.degraded}"
        )
