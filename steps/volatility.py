import logging
from typing import List

from steps.base import Step
from models.market import PriceData, VolatilityAlert, FrequencyType
from analyzers.volatility_analyzer import VolatilityAnalyzer
from analyzers.threshold_manager import ThresholdManager


class VolatilityStep(Step):
    """分析价格数据的波动，返回告警列表。

    输入：list[PriceData]
    输出：list[VolatilityAlert]（仅包含触发告警的）
    """

    def __init__(self):
        self.name = "VolatilityStep"
        self.threshold_manager = ThresholdManager()
        self.volatility_analyzer = VolatilityAnalyzer(self.threshold_manager)

    async def process(self, items: list) -> List[VolatilityAlert]:
        alerts: List[VolatilityAlert] = []

        for price_data in items:
            if not isinstance(price_data, PriceData):
                continue

            frequency = FrequencyType(price_data.frequency)

            if frequency == FrequencyType.MINUTE:
                alert = self.volatility_analyzer.analyze_minute_volatility(price_data)
            elif frequency == FrequencyType.DAILY:
                alert = self.volatility_analyzer.analyze_daily_volatility(price_data)
            elif frequency == FrequencyType.WEEKLY:
                alert = self.volatility_analyzer.analyze_weekly_volatility(price_data)
            else:
                alert = None

            if alert:
                alerts.append(alert)
                logging.info(
                    f"[{self.name}] 发现波动告警: {alert.name} {alert.current_change:.2f}%"
                )

        return alerts
