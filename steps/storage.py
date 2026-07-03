import logging

from steps.base import Step
from models.market import PriceData
from models.social import SocialPost, Briefing
from storage.market_db import MarketDataDB
from storage.social_store import SocialPostStore


class StorageStep(Step):
    """透传存储：根据领域对象类型分发存储，处理完后原样返回 items。"""

    def __init__(
        self,
        market_db: MarketDataDB | None = None,
        social_store: SocialPostStore | None = None,
    ):
        self.name = "StorageStep"
        self.market_db = market_db or MarketDataDB()
        self.social_store = social_store or SocialPostStore()

    async def process(self, items: list) -> list:
        posts = [x for x in items if isinstance(x, SocialPost)]
        if posts:
            n = self.social_store.save_posts(posts)
            logging.info(f"[{self.name}] social_posts saved: new={n} total={len(posts)}")

        for item in items:
            if isinstance(item, PriceData):
                self._store_price(item)
            elif isinstance(item, Briefing):
                self._store_briefing(item)

        return items

    def _store_price(self, price_data: PriceData):
        if self.market_db.save_price_data(price_data):
            logging.info(f"[{self.name}] 数据已保存: {price_data.symbol}")
        else:
            logging.info(f"[{self.name}] 数据已存在: {price_data.symbol}")

    def _store_briefing(self, briefing: Briefing):
        bid = self.social_store.save_briefing(briefing)
        logging.info(f"[{self.name}] briefing saved id={bid} degraded={briefing.degraded}")
