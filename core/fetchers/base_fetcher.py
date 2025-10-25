from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from models.market_data import PriceData

class BaseFetcher(ABC):
    """数据获取器基类"""
    
    def __init__(self, api_config: dict):
        self.api_config = api_config
        self.session = None
    
    @abstractmethod
    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """获取实时数据"""
        pass
    
    @abstractmethod
    async def fetch_historical_data(self, symbol: str, frequency: str, 
                                  start_date: datetime, 
                                  end_date: Optional[datetime] = None) -> List[PriceData]:
        """获取指定日期时间的历史数据
        
        Args:
            symbol: 股票代码
            frequency: 数据频率 ('1m', '5m', '1d', '1w', etc.)
            start_date: 开始日期时间
            end_date: 结束日期时间 (默认为当前时间)
        """
        pass
    
    def calculate_change_percent(self, current: float, previous: float) -> float:
        """计算涨跌幅"""
        if previous == 0:
            return 0.0
        return (current - previous) / previous * 100