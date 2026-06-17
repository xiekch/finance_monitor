from datetime import datetime
from typing import Any

from steps.base import Step
from models.messages import MarketBriefingMessage
from utils.time_util import utc_now_iso


class MarketBriefingStep(Step):

    def __init__(self):
        self.name = "MarketBriefingStep"

    async def process(self, data: Any) -> MarketBriefingMessage | None:
        if not data:
            return None

        market_block = data.get("market_block", "")
        if not market_block.strip():
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        markdown = f"📊 每日行情早报 {today}\n\n{market_block}"

        payload = {
            "markdown": markdown,
            "created_at": utc_now_iso(),
        }
        return MarketBriefingMessage(payload=payload, source=self.name)
