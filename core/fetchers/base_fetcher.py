from abc import ABC, abstractmethod
from typing import List, Optional
from models.market_data import PriceData

class BaseFetcher(ABC):
    """数据获取器基类"""
    
    def __init__(self, api_config: dict):
        self.api_config = api_config
        self.session = None
    
    @abstractmethod
    async def fetch_realtime_data(self, symbols: List[str]) -> List[PriceData]:
        """获取实时数据"""
        pass
    
    @abstractmethod
    async def fetch_historical_data(self, symbol: str, frequency: str, 
                                  limit: int = 100) -> List[PriceData]:
        """获取历史数据"""
        pass
    
    def calculate_change_percent(self, current: float, previous: float) -> float:
        """计算涨跌幅"""
        if previous == 0:
            return 0.0
        return (current - previous) / previous * 100