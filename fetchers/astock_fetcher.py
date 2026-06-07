import aiohttp
import asyncio
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from .base_fetcher import BaseFetcher
from models.market import PriceData
from storage.market_db import MarketDataDB
from infra.trading_hours import TradingHoursManager

class AStockFetcher(BaseFetcher):
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
            
            # 并行获取实时数据；写库职责由 StorageConsumer 统一承担，fetcher 不再直接写库
            if tasks:
                realtime_results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in realtime_results:
                    if isinstance(result, PriceData):
                        results.append(result)

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
            logging.warning(f"[AStockFetcher] 未知市场类型: {market} for symbol {symbol}")
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
                    logging.error(f"[AStockFetcher] iTick API错误: {response.status}")
                    return None

        except Exception as e:
            logging.error(f"[AStockFetcher] iTick 数据获取失败 {symbol_info['name']}: {e}")
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
                    logging.error(f"[AStockFetcher] Finage API错误: {response.status}")
                    return None

        except Exception as e:
            logging.error(f"[AStockFetcher] Finage 数据获取失败 {symbol_info['name']}: {e}")
            return None
    
    async def fetch_historical_data(
        self,
        symbol: str,
        frequency: str = '1d',
        limit: int = 100,
        market: str = '',
    ) -> List[PriceData]:
        """A 股指数日/周线历史数据，走 akshare sina backend。

        前置：MONITOR_CONFIG 里的 A 股 daily/weekly 当前全部是指数
        （沪深300 / 创业板指等），sina 个股 endpoint 在本机会被 reset，
        所以暂时只支持指数。需要加个股时再扩 endpoint。
        """
        if frequency not in ('1d', '1w'):
            logging.error(f"[AStockFetcher] 不支持的历史频率: {frequency}")
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_index_historical_sync, symbol, market, frequency, limit,
        )

    def _fetch_index_historical_sync(
        self, symbol: str, market: str, frequency: str, limit: int,
    ) -> List[PriceData]:
        try:
            import akshare as ak
            import pandas as pd
        except ImportError:
            logging.error("[AStockFetcher] akshare/pandas 未安装，无法拉取 A 股历史数据")
            return []

        market_upper = (market or '').upper()
        if market_upper not in ('SH', 'SZ'):
            logging.error(
                f"[AStockFetcher] 历史数据仅支持 SH/SZ 指数, 收到 market={market!r} symbol={symbol}"
            )
            return []
        ak_symbol = f"{market_upper.lower()}{symbol}"

        try:
            df = ak.stock_zh_index_daily(symbol=ak_symbol)
        except Exception as e:
            logging.error(f"[AStockFetcher] akshare 拉取 {ak_symbol} 失败: {e}")
            return []
        if df is None or df.empty:
            logging.warning(f"[AStockFetcher] akshare {ak_symbol} 返回空")
            return []

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()

        if frequency == '1w':
            # W-FRI: 以周五为一周收盘（自然周对齐 A 股交易周）
            df = df.resample('W-FRI').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum',
            }).dropna()

        df = df.tail(limit)
        return [
            PriceData(
                symbol=symbol,
                market=market_upper,
                timestamp=ts.to_pydatetime(),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume']),
                frequency=frequency,
            )
            for ts, row in df.iterrows()
        ]