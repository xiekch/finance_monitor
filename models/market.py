from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class PriceData:
    symbol: str
    market: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    frequency: str = '1m'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'market': self.market,
            'timestamp': self.timestamp.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'frequency': self.frequency
        }

@dataclass
class VolatilityAlert:
    """波动率预警类（完整版）"""

    symbol: str
    name: str
    frequency: str
    current_change: float
    threshold: float
    current_price: float
    previous_price: float
    timestamp: datetime
    volume: Optional[float] = None
