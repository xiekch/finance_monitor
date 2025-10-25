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
                        symbol=data.symbol,
                        market='US',
                        frequency=FrequencyType.MINUTE,
                        price_data=data.to_dict(),
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
        
        try:
            # 获取美股标的
            us_stock_symbols = self._get_us_stock_symbols('daily')
            
            if not us_stock_symbols:
                logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
                return messages
            
            logging.info(f"[{self.producer_name}] 开始处理 {len(us_stock_symbols)} 个美股标的")
            
            # 设置日期范围 - 获取最近一个交易日的数据
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)  # 获取最近7天的数据确保包含交易日
            
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
                        # 获取最新的数据（最后一条）
                        data = historical_data[-1]
                        
                        # 检查数据是否为最近交易日的数据
                        data_date = data.timestamp.date()
                        today = datetime.now().date()
                        
                        # 如果数据日期不是今天，说明是历史数据，记录日志
                        if data_date != today:
                            logging.info(f"[{self.producer_name}] {symbol} 获取到历史数据，日期: {data_date}")
                        
                        message = PriceDataMessage(
                            symbol=data.symbol,
                            market='US',
                            frequency=FrequencyType.DAILY,
                            price_data=data.to_dict(),
                            source=self.producer_name,
                            timestamp=datetime.now()
                        )
                        messages.append(message)
                        
                        logging.info(f"[{self.producer_name}] 生产日线数据: {data.symbol} "
                                   f"收盘价: ${data.close:.2f}, 日期: {data_date}")
                    else:
                        logging.warning(f"[{self.producer_name}] 未获取到 {symbol} 的日线数据")
                        
                except Exception as e:
                    logging.error(f"[{self.producer_name}] 处理标的 {symbol_info.get('symbol')} 失败: {e}")
                    continue
        
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产美股日线数据失败: {e}")
        
        logging.info(f"[{self.producer_name}] 生产完成，共生成 {len(messages)} 条日线数据")
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
            
            # 设置日期范围 - 获取指定日期的数据
            start_date = target_date
            end_date = target_date + timedelta(days=1)
            
            for symbol_info in us_stock_symbols:
                try:
                    symbol = symbol_info['symbol']
                    
                    # 获取指定日期的数据
                    historical_data = await self.us_stock_fetcher.fetch_historical_data(
                        symbol=symbol,
                        frequency='1d',
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    if historical_data and len(historical_data) > 0:
                        # 检查数据日期是否匹配目标日期
                        matching_data = []
                        for data in historical_data:
                            if data.timestamp.date() == target_date.date():
                                matching_data.append(data)
                        
                        if matching_data:
                            # 取第一条匹配的数据（应该只有一条）
                            data = matching_data[0]
                            
                            message = PriceDataMessage(
                                symbol=data.symbol,
                                market='US',
                                frequency=FrequencyType.DAILY,
                                price_data=data.to_dict(),
                                source=f"{self.producer_name}_SpecificDate",
                                timestamp=datetime.now()
                            )
                            messages.append(message)
                            
                            logging.info(f"[{self.producer_name}] 生产指定日期日线数据: {data.symbol} "
                                       f"收盘价: ${data.close:.2f}, 日期: {target_date.strftime('%Y-%m-%d')}")
                        else:
                            logging.warning(f"[{self.producer_name}] {symbol} 在 {target_date.strftime('%Y-%m-%d')} 无交易数据")
                    else:
                        logging.warning(f"[{self.producer_name}] 未获取到 {symbol} 在 {target_date.strftime('%Y-%m-%d')} 的日线数据")
                        
                except Exception as e:
                    logging.error(f"[{self.producer_name}] 处理标的 {symbol_info.get('symbol')} 的指定日期数据失败: {e}")
                    continue
        
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产指定日期美股日线数据失败: {e}")
        
        logging.info(f"[{self.producer_name}] 指定日期数据生产完成，共生成 {len(messages)} 条日线数据")
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
                            symbol=data.symbol,
                            market='US',
                            frequency=FrequencyType.WEEKLY,
                            price_data=data.to_dict(),
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


class USStockExtendedHoursProducer(BaseProducer):
    """美股盘前盘后数据生产者"""
    
    def __init__(self):
        super().__init__("USStockExtendedHoursProducer")
        self.us_stock_fetcher = USStockYfFetcher(API_CONFIG)
    
    def create_trigger(self) -> CronTrigger:
        """
        创建盘前盘后调度触发器
        盘前：北京时间晚上7-9点
        盘后：北京时间凌晨4-6点
        """
        return CronTrigger(
            hour='19-21,4-6',  # 盘前和盘后时间段
            minute='*/10',      # 每10分钟
            day_of_week='mon-fri'
        )
    
    async def produce_data(self) -> List[PriceDataMessage]:
        """生产美股盘前盘后数据"""
        messages = []
        
        try:
            # 获取美股标的
            us_stock_symbols = self._get_us_stock_symbols('minute')
            
            if not us_stock_symbols:
                logging.warning(f"[{self.producer_name}] 未找到美股标的配置")
                return messages
            
            # 获取实时数据（在盘前盘后时间段会包含扩展交易数据）
            stock_data = await self.us_stock_fetcher.fetch_realtime_data(us_stock_symbols)
            
            for data in stock_data:
                if data:
                    message = PriceDataMessage(
                        symbol=data.symbol,
                        market='US',
                        frequency=FrequencyType.MINUTE,
                        price_data=data.to_dict(),
                        source=self.producer_name,
                        timestamp=datetime.now(),
                        extra_info={'session': 'extended'}  # 标记为扩展交易时段
                    )
                    messages.append(message)
                    logging.info(f"[{self.producer_name}] 生产盘前盘后数据: {data.symbol} ${data.close:.2f}")
            
            logging.info(f"[{self.producer_name}] 生产完成，共生成 {len(messages)} 条盘前盘后数据")
            
        except Exception as e:
            logging.error(f"[{self.producer_name}] 生产美股盘前盘后数据失败: {e}")
        
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