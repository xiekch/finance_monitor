import aiohttp
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta

from .base_fetcher import BaseFetcher
from models.market_data import PriceData, MarketDataDB
from core.trading_hours import TradingHoursManager

class StockFetcher(BaseFetcher):
    """股票数据获取器"""
    
    def __init__(self, api_config: dict):
        super().__init__(api_config)
        self.trading_hours_manager = TradingHoursManager()
        self.db = MarketDataDB()
    
    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """获取股票实时数据"""
        results = []
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for symbol_info in symbols:
                market_type = self.trading_hours_manager.get_market_type(
                    symbol_info['symbol'], symbol_info.get('market', '')
                )
                
                # 检查交易时间
                if self.trading_hours_manager.is_trading_time(market_type):
                    task = self._fetch_single_stock(session, symbol_info)
                    tasks.append(task)
                else:
                    # 非交易时间，从数据库获取最新数据
                    latest_data = self._get_latest_from_db(symbol_info)
                    if latest_data:
                        results.append(latest_data)
            
            # 并行获取实时数据
            if tasks:
                realtime_results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in realtime_results:
                    if isinstance(result, PriceData):
                        results.append(result)
                        # 保存到数据库
                        self.db.save_price_data(result)
        
        return results
    
    def _get_latest_from_db(self, symbol_info: dict) -> Optional[PriceData]:
        """从数据库获取最新数据"""
        return self.db.get_latest_price(
            symbol=symbol_info['symbol'],
            market=symbol_info.get('market', ''),
            frequency='1m'
        )
    
    async def _fetch_single_stock(self, session: aiohttp.ClientSession, 
                                symbol_info: dict) -> Optional[PriceData]:
        """获取单只股票数据"""
        market = symbol_info.get('market', '')
        symbol = symbol_info['symbol']
        
        if market in ['SH', 'SZ', 'HK', 'FUT']:
            return await self._fetch_itick_data(session, symbol_info)
        elif market in ['US', 'NASDAQ', 'NYSE']:
            return await self._fetch_finage_data(session, symbol_info)
        else:
            print(f"未知市场类型: {market} for symbol {symbol}")
            return None
    
    async def _fetch_itick_data(self, session: aiohttp.ClientSession, 
                              symbol_info: dict) -> Optional[PriceData]:
        """从iTick获取A股/港股/期货数据"""
        url = f"{self.api_config['itick']['base_url']}/stock/kline"
        params = {
            'region': symbol_info['market'],
            'code': symbol_info['symbol'],
            'kType': '1'  # 1分钟K线
        }
        headers = {
            'accept': 'application/json',
            'token': self.api_config['itick']['token']
        }
        
        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if 'data' in data and len(data['data']) >= 1:
                        latest = data['data'][-1]
                        return PriceData(
                            symbol=symbol_info['symbol'],
                            market=symbol_info['market'],
                            timestamp=datetime.now(),
                            open=latest.get('open', 0),
                            high=latest.get('high', 0),
                            low=latest.get('low', 0),
                            close=latest.get('close', 0),
                            volume=latest.get('volume', 0),
                            frequency='1m'
                        )
                else:
                    print(f"iTick API错误: {response.status}")
                    return None
                    
        except Exception as e:
            print(f"iTick数据获取失败 {symbol_info['name']}: {e}")
            return None
    
    async def _fetch_finage_data(self, session: aiohttp.ClientSession, 
                               symbol_info: dict) -> Optional[PriceData]:
        """从Finage获取美股数据"""
        symbol = symbol_info['symbol']
        url = f"{self.api_config['finage']['base_url']}/last/stock/{symbol}"
        params = {
            'apikey': self.api_config['finage']['api_key']
        }
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Finage返回的数据结构可能不同，这里需要根据实际API调整
                    return PriceData(
                        symbol=symbol,
                        market=symbol_info.get('market', 'US'),
                        timestamp=datetime.now(),
                        open=data.get('open', 0),
                        high=data.get('high', 0),
                        low=data.get('low', 0),
                        close=data.get('ask', data.get('price', 0)),  # 使用卖一价或最新价
                        volume=data.get('volume', 0),
                        frequency='1m'
                    )
                else:
                    print(f"Finage API错误: {response.status}")
                    return None
                    
        except Exception as e:
            print(f"Finage数据获取失败 {symbol_info['name']}: {e}")
            return None
    
    async def fetch_historical_data(self, symbol: str, frequency: str = '1d', 
                                  limit: int = 100) -> List[PriceData]:
        """获取股票历史数据"""
        # 这里可以实现从数据库或API获取历史数据
        # 简化实现：从数据库获取
        end_date = datetime.now()
        
        # 根据频率计算开始日期
        if frequency == '1m':
            start_date = end_date - timedelta(days=1)
        elif frequency == '1d':
            start_date = end_date - timedelta(days=limit)
        elif frequency == '1w':
            start_date = end_date - timedelta(weeks=limit)
        else:
            start_date = end_date - timedelta(days=30)
        
        return self.db.get_historical_prices(
            symbol=symbol, 
            market='',  # 需要根据实际情况确定market
            frequency=frequency,
            start_date=start_date,
            end_date=end_date
        )