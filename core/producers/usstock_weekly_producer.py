from typing import List
from datetime import datetime, timedelta
import logging
from apscheduler.triggers.cron import CronTrigger
from .base_producer import BaseProducer
from core.message_types import PriceDataMessage, FrequencyType, MessageType
from core.fetchers.us_stock_yf_fetcher import USStockYfFetcher
from config.settings import API_CONFIG, MONITOR_CONFIG


class USStockWeeklyProducer(BaseProducer):
    """美股周级数据生产者"""
    
    def __init__(self, run_immediately: bool = False, ignore_schedule: bool = False):
        super().__init__("USStockWeeklyProducer", run_immediately, ignore_schedule)
        self.us_stock_fetcher = USStockYfFetcher(API_CONFIG)
    
    def create_trigger(self) -> CronTrigger:
        """
        创建周级调度触发器
        每周一早上运行（获取上周数据）
        """
        return CronTrigger(
            day_of_week='mon',  # 每周一
            hour=6,             # 北京时间早上6点
            minute=0,
            second=0
        )
    
    async def produce_data(self) -> List[PriceDataMessage]:
        """生产美股周级数据"""
        messages = []
        
        try:
            # 获取美股标的
            us_stock_symbols = self._get_us_stock_symbols('weekly')
            
            if not us_stock_symbols:
                logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
                return messages
            
            logging.info(f"[{self.producer_name}] 开始处理 {len(us_stock_symbols)} 个美股标的")
            
            for symbol_info in us_stock_symbols:
                try:
                    symbol = symbol_info['symbol']
                    
                    # 获取周线数据
                    historical_data = await self.us_stock_fetcher.fetch_historical_data(
                        symbol=symbol,
                        frequency='1w',
                        limit=1  # 只需要最近一周
                    )
                    
                    if historical_data and len(historical_data) > 0:
                        data = historical_data[0]
                        
                        message = PriceDataMessage(
                            payload=data.to_dict(),
                            source=self.producer_name,
                            timestamp=datetime.now()
                        )
                        messages.append(message)
                        
                        logging.info(f"[{self.producer_name}] 生产周线数据: {data.symbol} "
                                   f"收盘价: ${data.close:.2f}, 周期: {data.timestamp.strftime('%Y-%m-%d')}")
                    else:
                        logging.warning(f"[{self.producer_name}] 未获取到 {symbol} 的周线数据")
                        
                except Exception as e:
                    logging.error(f"[{self.producer_name}] 处理标的 {symbol_info.get('symbol')} 失败: {e}")
                    continue
        
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产美股周线数据失败: {e}")
        
        logging.info(f"[{self.producer_name}] 生产完成，共生成 {len(messages)} 条周线数据")
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
