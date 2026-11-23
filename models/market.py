from datetime import date, datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass


class FrequencyType(Enum):
    MINUTE = "1m"
    DAILY = "1d"
    WEEKLY = "1w"


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
    # 昨收。只有报价自带昨收的来源（新浪 A 股、港美股）会填，不入库、不序列化。
    prev_close: Optional[float] = None

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
    basis: str = ''  # 参考价是什么：昨收 / 30分钟前；空表示上一次轮询价（加密货币、期货的分钟级）


@dataclass
class NewStockListing:
    """一只当天上市的新股。拿不到的字段为 None。"""

    symbol: str
    name: str
    exchange: str  # 上交所 / 深交所 / 北交所
    board: str  # 主板 / 创业板 / 科创板 / 北交所 等
    listing_date: date
    issue_price: Optional[float] = None  # 发行价，元
    issue_pe: Optional[float] = None  # 发行市盈率
    industry_pe: Optional[float] = None  # 行业市盈率
    issue_shares: Optional[float] = None  # 发行总数，万股
    subscribe_date: Optional[date] = None  # 申购日


@dataclass
class MarketBriefing:
    """标的行情早报（已格式化的 markdown）。"""

    markdown: str
    created_at: str  # UTC ISO8601
