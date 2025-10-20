import asyncio
from typing import List
from datetime import datetime

from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType, MessageType
from core.fetchers.us_stock_yf_fetcher import USStockYfFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG

class USStockProducer(BaseProducer):
    """美股数据生产者"""
    
    def __init__(self):
        super().__init__("USStockProducer")
        self.us_stock_fetcher = USStockYfFetcher(API_CONFIG)
        self.frequency_mapping = {
            'minute': FrequencyType.MINUTE,
            'daily': FrequencyType.DAILY,
            'weekly': FrequencyType.WEEKLY
        }
    
    async def produce_data(self) -> List[PriceDataMessage]:
        """生产美股数据（异步版本）"""
        messages = []
        
        try:
            # 获取美股标的
            us_stock_symbols = self._get_us_stock_symbols('minute')
            if us_stock_symbols:
                stock_data = await self.us_stock_fetcher.fetch_realtime_data(us_stock_symbols)
                
                for data in stock_data:
                    if data:  # 确保数据有效
                        message = PriceDataMessage(
                            symbol=data.symbol,
                            market='US',  # 美股统一使用US市场代码
                            frequency=FrequencyType.MINUTE,
                            price_data=data.to_dict(),
                            source=self.producer_name
                        )
                        messages.append(message)
                        print(f"[{self.producer_name}] 生产美股数据: {data.symbol} ${data.close:.2f}")
        
        except Exception as e:
            print(f"[{self.producer_name}] 生产美股数据失败: {e}")
        
        return messages
    
    def _get_us_stock_symbols(self, frequency: str) -> List[dict]:
        """获取美股标的列表"""
        all_symbols = self._get_symbols_by_frequency(frequency, 'stocks')
        us_stock_symbols = []
        
        for symbol_info in all_symbols:
            market = symbol_info.get('market', '')
            symbol = symbol_info.get('symbol', '')
            # 选择美股（市场为US，或者符号是典型的美股代码）
            if market in ['US', 'NASDAQ', 'NYSE'] or self._is_us_stock_symbol(symbol):
                us_stock_symbols.append({
                    'symbol': symbol,
                    'market': 'US',  # 统一标记为US
                    'name': symbol_info.get('name', symbol),
                    'threshold': symbol_info.get('threshold', 2.0)
                })
        
        return us_stock_symbols
    
    def _is_us_stock_symbol(self, symbol: str) -> bool:
        """判断是否为美股符号"""
        # 美股通常为1-5个字母的代码
        if len(symbol) <= 5 and symbol.isalpha() and symbol.isupper():
            return True
        return False
    
    def _get_symbols_by_frequency(self, frequency: str, asset_type: str):
        """获取指定频率和资产类型的标的"""
        return MONITOR_CONFIG.get(frequency, {}).get(asset_type, [])
    
    async def produce_historical_data(self, frequency: FrequencyType):
        """生产美股历史数据"""
        try:
            us_stock_symbols = self._get_us_stock_symbols(frequency.value)
            historical_messages = []
            
            for symbol_info in us_stock_symbols:
                # 获取历史数据
                historical_data = await self.us_stock_fetcher.fetch_historical_data(
                    symbol=symbol_info['symbol'],
                    frequency=self._convert_frequency(frequency),
                    limit=100
                )
                
                for data in historical_data:
                    message = PriceDataMessage(
                        symbol=data.symbol,
                        market='US',
                        frequency=frequency,
                        price_data=data.to_dict(),
                        source=f"{self.producer_name}_Historical"
                    )
                    historical_messages.append(message)
            
            return historical_messages
            
        except Exception as e:
            print(f"[{self.producer_name}] 生产美股历史数据失败: {e}")
            return []
    
    def _convert_frequency(self, frequency: FrequencyType) -> str:
        """转换频率格式"""
        frequency_map = {
            FrequencyType.MINUTE: '1m',
            FrequencyType.DAILY: '1d',
            FrequencyType.WEEKLY: '1w'
        }
        return frequency_map.get(frequency, '1d')
    
    async def get_extended_hours_data(self, symbols: List[str]) -> List[PriceDataMessage]:
        """获取美股盘前盘后数据"""
        messages = []
        try:
            for symbol in symbols:
                # 使用yfinance获取盘前盘后数据
                extended_data = await self.us_stock_fetcher.get_extended_hours_data(symbol)
                if extended_data:
                    message = PriceDataMessage(
                        symbol=symbol,
                        market='US',
                        frequency=FrequencyType.MINUTE,
                        price_data=extended_data.to_dict(),
                        source=f"{self.producer_name}_Extended"
                    )
                    messages.append(message)
        
        except Exception as e:
            print(f"[{self.producer_name}] 获取盘前盘后数据失败: {e}")
        
        return messages