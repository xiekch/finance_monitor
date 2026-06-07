import logging
from typing import Any, List

from steps.base import Step
from models.messages import PriceDataMessage, VolatilityAlertMessage, FrequencyType
from models.market import PriceData
from analyzers.volatility_analyzer import VolatilityAnalyzer
from analyzers.threshold_manager import ThresholdManager


class VolatilityStep(Step):
    """分析价格数据的波动，返回告警列表。

    输入：list[PriceDataMessage]
    输出：list[VolatilityAlertMessage]（仅包含触发告警的）
    """

    def __init__(self):
        self.name = "VolatilityStep"
        self.threshold_manager = ThresholdManager()
        self.volatility_analyzer = VolatilityAnalyzer(self.threshold_manager)

    async def process(self, data: Any) -> List[VolatilityAlertMessage]:
        if not data:
            return []

        items = data if isinstance(data, list) else [data]
        alerts: List[VolatilityAlertMessage] = []

        for message in items:
            if not isinstance(message, PriceDataMessage):
                continue

            price_data = PriceData.from_dict(message.payload)
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
                alert_message = VolatilityAlertMessage(
                    payload={
                        "symbol": alert.symbol,
                        "name": alert.name,
                        "frequency": alert.frequency,
                        "current_change": alert.current_change,
                        "threshold": alert.threshold,
                        "current_price": alert.current_price,
                        "previous_price": alert.previous_price,
                        "timestamp": alert.timestamp.isoformat(),
                    },
                    source=self.name,
                )
                alerts.append(alert_message)
                logging.info(
                    f"[{self.name}] 发现波动告警: {alert.name} {alert.current_change:.2f}%"
                )

        return alerts if alerts else []
