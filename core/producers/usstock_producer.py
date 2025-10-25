import asyncio
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


class USStockDailyProducer(BaseProducer):
    """美股日级数据生产者"""
    
    def __init__(self, run_immediately: bool = False, ignore_schedule: bool = False):
        super().__init__("USStockDailyProducer", run_immediately, ignore_schedule)
        self.us_stock_fetcher = USStockYfFetcher(API_CONFIG)
    
    def create_trigger(self) -> CronTrigger:
        """
        创建日级调度触发器
        每天美股收盘后运行（北京时间凌晨5点）
        """
        return CronTrigger(
            hour=5,           # 北京时间凌晨5点
            minute=0,
            second=0,
            day_of_week='mon-fri'  # 只在工作日运行
        )
    
    async def produce_data(self) -> List[PriceDataMessage]:
        """生产美股日级数据"""
        messages = []
        
        # 获取美股标的
        us_stock_symbols = self._get_us_stock_symbols('daily')
        
        if not us_stock_symbols:
            logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
            return messages
        
        logging.info(f"[{self.producer_name}] 开始处理 {len(us_stock_symbols)} 个美股标的")
        
        # 设置日期范围 - 获取最近7天的数据确保包含交易日
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        for symbol_info in us_stock_symbols:
            try:
                symbol = symbol_info['symbol']
                
                # 使用新的接口获取日线数据
                historical_data = await self.us_stock_fetcher.fetch_historical_data(
                    symbol=symbol,
                    frequency='1d',
                    start_date=start_date,
                    end_date=end_date
                )
                
                if historical_data and len(historical_data) > 0:
                    # 处理所有历史数据
                    for i, data in enumerate(historical_data):
                        data_date = data.timestamp.date()
                        today = datetime.now().date()
                        
                        # 判断消息类型：最后一条为实时数据，其他为历史数据
                        if i == len(historical_data) - 1:
                            # 最后一条数据作为实时价格数据
                            message_type = MessageType.PRICE_DATA
                            log_prefix = "生产日线数据"
                            
                            # 如果数据日期不是今天，说明是历史数据
                            if data_date != today:
                                logging.info(f"[{self.producer_name}] {symbol} 获取到历史数据作为最新数据，日期: {data_date}")
                        else:
                            # 其他数据作为历史价格数据
                            message_type = MessageType.HISTORICAL_PRICE_DATA
                            log_prefix = "生产历史日线数据"
                        
                        message = PriceDataMessage(
                            payload=data.to_dict(),
                            source=self.producer_name,
                            timestamp=data.timestamp,
                            message_type=message_type
                        )
                        messages.append(message)
                        
                        logging.info(f"[{self.producer_name}] {log_prefix}: {data.symbol} "
                                    f"收盘价: ${data.close:.2f}, 日期: {data_date}, 类型: {message_type.value}")
                    
                    logging.info(f"[{self.producer_name}] {symbol} 共处理 {len(historical_data)} 条数据")
                else:
                    logging.warning(f"[{self.producer_name}] 未获取到 {symbol} 的日线数据")
                    
            except Exception as e:
                logging.error(f"[{self.producer_name}] 处理标的 {symbol_info.get('symbol')} 失败: {e}")
                continue

        # 统计不同类型消息的数量
        price_data_count = sum(1 for msg in messages if msg.message_type == MessageType.PRICE_DATA)
        historical_data_count = sum(1 for msg in messages if msg.message_type == MessageType.HISTORICAL_PRICE_DATA)
        
        logging.info(f"[{self.producer_name}] 生产完成，共生成 {len(messages)} 条数据 "
                   f"(实时: {price_data_count}, 历史: {historical_data_count})")
        return messages
    
    async def produce_specific_date_data(self, target_date: datetime) -> List[PriceDataMessage]:
        """生产指定日期的美股日线数据"""
        messages = []
        
        try:
            us_stock_symbols = self._get_us_stock_symbols('daily')
            
            if not us_stock_symbols:
                logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
                return messages
            
            logging.info(f"[{self.producer_name}] 开始处理 {len(us_stock_symbols)} 个美股标的的 {target_date.strftime('%Y-%m-%d')} 数据")
            
            # 设置日期范围 - 获取指定日期及前后几天的数据
            start_date = target_date - timedelta(days=3)
            end_date = target_date + timedelta(days=1)
            
            for symbol_info in us_stock_symbols:
                try:
                    symbol = symbol_info['symbol']
                    
                    # 获取指定日期范围的数据
                    historical_data = await self.us_stock_fetcher.fetch_historical_data(
                        symbol=symbol,
                        frequency='1d',
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    if historical_data and len(historical_data) > 0:
                        # 处理所有获取到的数据
                        for data in historical_data:
                            data_date = data.timestamp.date()
                            target_date_only = target_date.date()
                            
                            # 判断消息类型：目标日期数据为历史数据，其他日期数据也为历史数据
                            message_type = MessageType.HISTORICAL_PRICE_DATA
                            
                            # 检查数据日期是否匹配目标日期
                            if data_date == target_date_only:
                                log_prefix = "生产指定日期历史数据"
                            else:
                                log_prefix = "生产相关日期历史数据"
                            
                            message = PriceDataMessage(
                                payload=data.to_dict(),
                                source=f"{self.producer_name}_Historical",
                                timestamp=data.timestamp,
                                message_type=message_type
                            )
                            messages.append(message)
                            
                            logging.info(f"[{self.producer_name}] {log_prefix}: {data.symbol} "
                                       f"收盘价: ${data.close:.2f}, 日期: {data_date}")
                        
                        logging.info(f"[{self.producer_name}] {symbol} 在日期范围 {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')} 共获取 {len(historical_data)} 条数据")
                    else:
                        logging.warning(f"[{self.producer_name}] 未获取到 {symbol} 在指定日期范围的日线数据")
                        
                except Exception as e:
                    logging.error(f"[{self.producer_name}] 处理标的 {symbol_info.get('symbol')} 的指定日期数据失败: {e}")
                    continue
        
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产指定日期美股日线数据失败: {e}")
        
        logging.info(f"[{self.producer_name}] 指定日期数据生产完成，共生成 {len(messages)} 条历史数据")
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
