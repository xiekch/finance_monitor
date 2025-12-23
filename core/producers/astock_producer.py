import asyncio
from typing import Sequence, List
from datetime import datetime

from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType, MessageType
from core.fetchers.stock_fetcher import StockFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG

class AStockProducer(BaseProducer):
    """A股数据生产者"""
    
    def __init__(self):
        super().__init__("AStockProducer")
        self.stock_fetcher = StockFetcher(API_CONFIG)
        self.frequency_mapping = {
            'minute': FrequencyType.MINUTE,
            'daily': FrequencyType.DAILY,
            'weekly': FrequencyType.WEEKLY
        }
    
    async def produce_data(self) -> Sequence[PriceDataMessage]:
        """生产A股数据（异步版本）"""
        messages = []
        
        try:
            # 获取A股标的（过滤出SH和SZ市场的股票）
            a_stock_symbols = self._get_a_stock_symbols('minute')
            if a_stock_symbols:
                stock_data = await self.stock_fetcher.fetch_realtime_data(a_stock_symbols)
                
                for data in stock_data:
                    # 确保是A股数据
                    if data and data.market in ['SH', 'SZ']:
                        message = PriceDataMessage(
                            payload=data.to_dict(),
                            source=self.producer_name
                        )
                        messages.append(message)
                        print(f"[{self.producer_name}] 生产A股数据: {data.symbol} {data.close}")
        
        except Exception as e:
            print(f"[{self.producer_name}] 生产A股数据失败: {e}")
        
        return messages
    
    def _get_a_stock_symbols(self, frequency: str) -> List[dict]:
        """获取A股标的列表"""
        all_symbols = self._get_symbols_by_frequency(frequency, 'stocks')
        a_stock_symbols = []
        
        for symbol_info in all_symbols:
            market = symbol_info.get('market', '')
            # 只选择上海和深圳市场的股票
            if market in ['SH', 'SZ']:
                a_stock_symbols.append(symbol_info)
        
        return a_stock_symbols
    
    def _get_symbols_by_frequency(self, frequency: str, asset_type: str):
        """获取指定频率和资产类型的标的"""
        return MONITOR_CONFIG.get(frequency, {}).get(asset_type, [])
    
    async def produce_historical_data(self, frequency: FrequencyType):
        """生产A股历史数据"""
        try:
            a_stock_symbols = self._get_a_stock_symbols(frequency.value)
            historical_messages = []
            
            for symbol_info in a_stock_symbols:
                # 获取历史数据
                historical_data = await self.stock_fetcher.fetch_historical_data(
                    symbol=symbol_info['symbol'],
                    frequency=self._convert_frequency(frequency),
                    limit=100
                )
                
                for data in historical_data:
                    message = PriceDataMessage(
                        payload=data.to_dict(),
                        source=f"{self.producer_name}_Historical"
                    )
                    historical_messages.append(message)
            
            return historical_messages
            
        except Exception as e:
            print(f"[{self.producer_name}] 生产A股历史数据失败: {e}")
            return []
    
    def _convert_frequency(self, frequency: FrequencyType) -> str:
        """转换频率格式"""
        frequency_map = {
            FrequencyType.MINUTE: '1m',
            FrequencyType.DAILY: '1d',
            FrequencyType.WEEKLY: '1w'
        }
        return frequency_map.get(frequency, '1d')
