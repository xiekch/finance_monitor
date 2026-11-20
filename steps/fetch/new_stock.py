import logging
from datetime import date
from typing import List, Optional

from steps.base import Step
from models.market import NewStockListing
from fetchers.new_stock_fetcher import fetch_listings_on


class FetchNewStockListings(Step):
    """查今天上市的 A 股新股。没有就返回空列表，由通知步骤决定不发。"""

    def __init__(self, today: Optional[date] = None):
        self.name = "FetchNewStockListings"
        self._today = today

    async def process(self, items: list = ()) -> List[NewStockListing]:
        day = self._today or date.today()
        listings = await fetch_listings_on(day)
        logging.info(f"[{self.name}] {day} 上市新股 {len(listings)} 只")
        return listings
