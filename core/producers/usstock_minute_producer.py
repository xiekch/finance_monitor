from typing import List
from datetime import datetime, timedelta
import logging
from apscheduler.triggers.cron import CronTrigger
from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType, MessageType
from core.fetchers.us_stock_yf_fetcher import USStockYfFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG


class USStockMinuteProducer(BaseProducer):
    """美股分钟级数据生产者"""
    
    def __init__(self, interval_minutes: int = 5, run_immediately: bool = False, ignore_schedule: bool = False):
        super().__init__(f"USStockMinuteProducer_{interval_minutes}min", run_immediately, ignore_schedule)
        self.us_stock_fetcher = USStockYfFetcher(API_CONFIG)
        self.interval_minutes = interval_minutes
    
    def create_trigger(self) -> CronTrigger:
        """
        创建分钟级调度触发器
        在美股交易时间内每N分钟运行一次
        """
        return CronTrigger(
            hour='21-4',  # 北京时间晚上9点到次日凌晨4点（美东时间9:30-16:00）
            minute=f'*/{self.interval_minutes}',
            day_of_week='mon-fri'  # 只在周一到周五运行
        )
    
    async def produce_data(self) -> List[PriceDataMessage]:
        """生产美股分钟级数据"""
        messages = []
        
        try:
            # 获取美股标的
            us_stock_symbols = self._get_us_stock_symbols('minute')
            
            if not us_stock_symbols:
                logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
                return messages
            
            # 获取实时分钟数据
            stock_data = await self.us_stock_fetcher.fetch_realtime_data(us_stock_symbols)
            
            for data in stock_data:
                if data:  # 确保数据有效
                    message = PriceDataMessage(
                        payload=data.to_dict(),
                        source=self.producer_name,
                        timestamp=datetime.now()
                    )
                    messages.append(message)
                    logging.info(f"[{self.producer_name}] 生产分钟数据: {data.symbol} ${data.close:.2f}")
            
            logging.info(f"[{self.producer_name}] 生产完成，共生成 {len(messages)} 条分钟数据")
            
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产美股分钟数据失败: {e}")
        
        return messages
    
    def _get_us_stock_symbols(self, frequency: str) -> List[dict]:
        """获取美股标的列表"""
        all_symbols = self._get_symbols_by_frequency(frequency, 'stocks')
        us_stock_symbols = []
        
        for symbol_info in all_symbols:
            market = symbol_info.get('market', '')
            symbol = symbol_info.get('symbol', '')
            if market in ['US', 'NASDAQ', 'NYSE'] or self._is_us_stock_symbol(symbol):
                us_stock_symbols.append({
                    'symbol': symbol,
                    'market': 'US',
                    'name': symbol_info.get('name', symbol),
                    'threshold': symbol_info.get('threshold', 2.0)
                })
        
        return us_stock_symbols
    
    def _is_us_stock_symbol(self, symbol: str) -> bool:
        """判断是否为美股符号"""
        if len(symbol) <= 5 and symbol.isalpha() and symbol.isupper():
            return True
        return False
    
    def _get_symbols_by_frequency(self, frequency: str, asset_type: str):
        """获取指定频率和资产类型的标的"""
        return MONITOR_CONFIG.get(frequency, {}).get(asset_type, [])
