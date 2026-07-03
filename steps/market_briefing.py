from datetime import datetime
from typing import List

from steps.base import Step
from models.market import MarketBriefing
from models.social import MorningData
from utils.time_util import utc_now_iso


class MarketBriefingStep(Step):
    """把早报原料中的行情块格式化为行情早报。

    输入：list[MorningData]
    输出：list[MarketBriefing]
    """

    def __init__(self):
        self.name = "MarketBriefingStep"

    async def process(self, items: list) -> List[MarketBriefing]:
        data = next((x for x in items if isinstance(x, MorningData)), None)
        if data is None:
            return []

        market_block = data.market_block
        if not market_block.strip():
            return []

        today = datetime.now().strftime("%Y-%m-%d")
        markdown = f"📊 每日行情早报 {today}\n\n{market_block}"

        return [MarketBriefing(markdown=markdown, created_at=utc_now_iso())]
