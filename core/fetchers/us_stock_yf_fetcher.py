import yfinance as yf
import asyncio
import aiohttp
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

# 假设的BaseFetcher和PriceData，请根据您的实际定义调整
from .base_fetcher import BaseFetcher
from models.market_data import PriceData

class USStockYfFetcher(BaseFetcher):
    """
    基于Yahoo Finance API的美股数据获取器
    使用yfinance库免费获取数据:cite[4]:cite[7]
    """
    
    def __init__(self, api_config: dict = None):
        super().__init__(api_config or {})
        self.logger = logging.getLogger(__name__)
        
    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """
        获取美股实时报价数据
        
        Args:
            symbols: 股票符号列表，如 [{'symbol': 'AAPL'}, {'symbol': 'MSFT'}]
            
        Returns:
            List[PriceData]: 价格数据对象列表
        """
        self.logger.info(f"开始获取实时数据，标的: {[s['symbol'] for s in symbols]}")
        
        # 将异步操作委托给线程池执行，因为yfinance是同步库
        loop = asyncio.get_event_loop()
        try:
            # 获取实时报价数据:cite[1]
            stock_data = await loop.run_in_executor(
                None, 
                self._fetch_realtime_sync, 
                [s['symbol'] for s in symbols]
            )
            
            results = []
            for data in stock_data:
                if data:
                    price_data = self._create_price_data(data)
                    results.append(price_data)
                    
            self.logger.info(f"实时数据获取完成，成功: {len(results)}/{len(symbols)}")
            return results
            
        except Exception as e:
            self.logger.error(f"获取实时数据失败: {e}")
            return []

    async def fetch_historical_data(self, symbol: str, frequency: str = '1d', 
                                  limit: int = 100) -> List[PriceData]:
        """
        获取美股历史数据
        
        Args:
            symbol: 股票符号
            frequency: 数据频率 - 1m, 5m, 15m, 1h, 1d, 1w:cite[4]
            limit: 数据点数量限制
            
        Returns:
            List[PriceData]: 历史价格数据列表
        """
        self.logger.info(f"获取历史数据: {symbol}, 频率: {frequency}, 限制: {limit}")
        
        loop = asyncio.get_event_loop()
        try:
            # 获取历史数据:cite[4]:cite[7]
            history_data = await loop.run_in_executor(
                None,
                self._fetch_historical_sync,
                symbol,
                frequency,
                limit
            )
            
            historical_prices = []
            for _, row in history_data.iterrows():
                price_data = PriceData(
                    symbol=symbol,
                    market='US',
                    timestamp=row.name.to_pydatetime(),
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=float(row['Volume']),
                    frequency=frequency
                )
                historical_prices.append(price_data)
                
            self.logger.info(f"历史数据获取完成: {symbol}, 获取到 {len(historical_prices)} 条记录")
            return historical_prices[::-1]  # 返回时间升序排列的数据
            
        except Exception as e:
            self.logger.error(f"获取历史数据失败 {symbol}: {e}")
            return []

    def _fetch_realtime_sync(self, symbols: List[str]) -> List[Optional[Dict]]:
        """同步获取实时数据"""
        try:
            # 使用yfinance获取多个股票的实时数据:cite[4]
            tickers = yf.Tickers(" ".join(symbols))
            results = []
            
            for symbol in symbols:
                try:
                    ticker = tickers.tickers[symbol]
                    info = ticker.info
                    history = ticker.history(period="1d", interval="1m")
                    
                    if not history.empty:
                        latest = history.iloc[-1]
                        data = {
                            'symbol': symbol,
                            'timestamp': datetime.now(),
                            'open': float(latest['Open']),
                            'high': float(latest['High']),
                            'low': float(latest['Low']),
                            'close': float(latest['Close']),
                            'volume': float(latest['Volume']),
                            'info': info
                        }
                        results.append(data)
                    else:
                        # 回退到info接口
                        data = {
                            'symbol': symbol,
                            'timestamp': datetime.now(),
                            'open': info.get('open', 0),
                            'high': info.get('dayHigh', 0),
                            'low': info.get('dayLow', 0),
                            'close': info.get('currentPrice', info.get('regularMarketPrice', 0)),
                            'volume': info.get('volume', 0),
                            'info': info
                        }
                        results.append(data)
                        
                except Exception as e:
                    self.logger.warning(f"获取股票 {symbol} 实时数据失败: {e}")
                    results.append(None)
                    
            return results
            
        except Exception as e:
            self.logger.error(f"批量获取实时数据失败: {e}")
            return [None] * len(symbols)

    def _fetch_historical_sync(self, symbol: str, frequency: str, limit: int):
        """同步获取历史数据"""
        try:
            ticker = yf.Ticker(symbol)
            
            # 根据限制计算周期
            period_map = {
                100: '5d', 500: '1mo', 1000: '3mo', 
                2000: '6mo', 3000: '1y', 'max': 'max'
            }
            
            period = '5d'
            for key, value in period_map.items():
                if limit <= key:
                    period = value
                    break
            
            # 映射频率参数:cite[4]
            interval_map = {
                '1m': '1m', '5m': '5m', '15m': '15m',
                '1h': '1h', '1d': '1d', '1w': '1wk'
            }
            
            interval = interval_map.get(frequency, '1d')
            
            # 获取历史数据:cite[4]:cite[7]
            history = ticker.history(period=period, interval=interval)
            
            if len(history) > limit:
                history = history.tail(limit)
                
            return history
            
        except Exception as e:
            self.logger.error(f"同步获取历史数据失败 {symbol}: {e}")
            raise

    def _create_price_data(self, data: Dict) -> PriceData:
        """创建PriceData对象"""
        return PriceData(
            symbol=data['symbol'],
            market='US',
            timestamp=data['timestamp'],
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume'],
            frequency='1m'  # 实时数据默认为1分钟频率
        )

    async def get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取公司基本信息:cite[1]"""
        loop = asyncio.get_event_loop()
        try:
            def sync_fetch():
                ticker = yf.Ticker(symbol)
                return ticker.info
            
            info = await loop.run_in_executor(None, sync_fetch)
            return info
        except Exception as e:
            self.logger.error(f"获取公司信息失败 {symbol}: {e}")
            return None

    async def search_symbols(self, query: str) -> List[Dict]:
        """搜索股票符号:cite[1]"""
        loop = asyncio.get_event_loop()
        try:
            def sync_search():
                import yfinance as yf
                # 注意: yfinance的搜索功能可能有限，这里简单实现
                ticker = yf.Ticker(query)
                info = ticker.info
                return [{
                    'symbol': info.get('symbol', query),
                    'name': info.get('longName', ''),
                    'exchange': info.get('exchange', '')
                }]
            
            results = await loop.run_in_executor(None, sync_search)
            return results
        except Exception as e:
            self.logger.error(f"搜索股票符号失败 {query}: {e}")
            return []