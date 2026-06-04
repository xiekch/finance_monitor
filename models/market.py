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

    def __post_init__(self):
        # payload 跨进程/线程传输后 timestamp 常以 ISO 字符串形态出现，
        # 这里统一兜底解析，避免下游 (analyzer / db) 拿到 str 当 datetime 用。
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PriceData':
        return cls(
            symbol=data['symbol'],
            market=data['market'],
            timestamp=data['timestamp'],
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data.get('volume', 0),
            frequency=data.get('frequency', '1m'),
        )

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
