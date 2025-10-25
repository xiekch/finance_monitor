import yfinance as yf
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta
from .base_fetcher import BaseFetcher
from models.market_data import PriceData, MarketDataDB
from core.trading_hours import TradingHoursManager
import logging


class USStockYfFetcher(BaseFetcher):
    """使用 yfinance 获取美股数据的获取器"""

    def __init__(self, api_config: dict = None):
        super().__init__(api_config or {})
        self.trading_hours_manager = TradingHoursManager()
        self.db = MarketDataDB()

    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """获取美股实时数据"""
        results = []

        # 过滤出美股标的
        us_symbols = [
            symbol_info
            for symbol_info in symbols
            if symbol_info.get("market") in ["US", "NASDAQ", "NYSE"]
        ]

        if not us_symbols:
            return results

        # 检查交易时间
        market_type = "US"
        # if self.trading_hours_manager.is_trading_time(market_type):
            # 交易时间，从 yfinance 获取实时数据
        realtime_results = await self._fetch_yfinance_realtime(us_symbols)
        for result in realtime_results:
            if isinstance(result, PriceData):
                results.append(result)
                logging.debug(f"result {result}")
        # else:
        #     # 非交易时间，从数据库获取最新数据
        #     for symbol_info in us_symbols:
        #         latest_data = self._get_latest_from_db(symbol_info)
        #         if latest_data:
        #             results.append(latest_data)

        return results

    async def _fetch_yfinance_realtime(self, symbols: List[dict]) -> List[PriceData]:
        """使用 yfinance 获取实时数据"""
        tasks = []
        for symbol_info in symbols:
            task = self._fetch_single_stock(symbol_info)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [result for result in results if isinstance(result, PriceData)]

    async def _fetch_single_stock(self, symbol_info: dict) -> Optional[PriceData]:
        """获取单只股票数据"""
        try:
            # yfinance 的股票代码格式，如 AAPL, TSLA 等
            symbol = symbol_info["symbol"]

            # 创建 ticker 对象
            ticker = yf.Ticker(symbol)

            # 获取实时数据
            info = ticker.info
            history = ticker.history(period="1d", interval="1m")

            if history.empty:
                logging.error(f"yfinance 未返回数据 for {symbol}")
                return None

            logging.debug(f"history {history}")
            # 获取最新的一分钟数据
            latest = history.iloc[-1]

            return PriceData(
                symbol=symbol,
                market=symbol_info.get("market", "US"),
                timestamp=datetime.now(),
                open=float(latest["Open"]),
                high=float(latest["High"]),
                low=float(latest["Low"]),
                close=float(latest["Close"]),
                volume=int(latest["Volume"]),
                frequency="1m"
            )

        except Exception as e:
            logging.error(
                f"yfinance 数据获取失败 {symbol_info.get('name', symbol_info['symbol'])}: {e}"
            )
            return None

    def _get_latest_from_db(self, symbol_info: dict) -> Optional[PriceData]:
        """从数据库获取最新数据"""
        return self.db.get_latest_price(
            symbol=symbol_info["symbol"],
            market=symbol_info.get("market", "US"),
            frequency="1m",
        )

    async def fetch_historical_data(
        self, symbol: str, frequency: str = "1d", 
        start_date: datetime = None, 
        end_date: Optional[datetime] = None
    ) -> List[PriceData]:
        """获取指定日期时间的股票历史数据
        
        Args:
            symbol: 股票代码
            frequency: 数据频率
            start_date: 开始日期时间
            end_date: 结束日期时间 (默认为当前时间)
        """
        # 设置默认值
        if end_date is None:
            end_date = datetime.now()
        
        if start_date is None:
            # 如果没有指定开始日期，默认获取最近30天的数据
            start_date = end_date - timedelta(days=30)
        
        try:
            # 将频率转换为 yfinance 支持的格式
            yf_interval = self._convert_frequency(frequency)
            
            # 格式化日期为字符串
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")
            
            ticker = yf.Ticker(symbol)
            
            # 使用 start 和 end 参数获取指定时间范围的数据
            history = ticker.history(
                start=start_date, 
                end=end_date, 
                interval=yf_interval,
                auto_adjust=False  # 不自动调整价格
            )
            
            if history.empty:
                logging.warning(f"yfinance 未返回指定时间段的历史数据 for {symbol} ({start_str} to {end_str})")
                # 尝试从数据库获取
                return self._get_historical_from_db(symbol, frequency, start_date, end_date)
            
            price_data_list = []
            for timestamp, row in history.iterrows():
                # 跳过包含 NaN 值的行
                if row.isnull().any():
                    continue
                    
                price_data = PriceData(
                    symbol=symbol,
                    market="US",
                    timestamp=timestamp.to_pydatetime(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    frequency=frequency,
                )
                price_data_list.append(price_data)
                logging.debug(f"price_data {price_data}")
            
            logging.info(f"从 yfinance 获取了 {symbol} 的 {len(price_data_list)} 条历史数据 "
                        f"({start_str} 到 {end_str}, 频率: {frequency})")
            
            return price_data_list

        except Exception as e:
            logging.error(f"yfinance 历史数据获取失败 {symbol}: {e}")
            # 失败时从数据库获取
            return self._get_historical_from_db(symbol, frequency, start_date, end_date)

    def _convert_frequency(self, frequency: str) -> str:
        """将频率转换为 yfinance 支持的格式"""
        frequency_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "1d": "1d",
            "1w": "1wk",
            "1M": "1mo",
        }
        return frequency_map.get(frequency, "1d")

    def _get_historical_from_db(
        self, symbol: str, frequency: str, start_date: datetime, end_date: datetime
    ) -> List[PriceData]:
        """从数据库获取指定时间范围的历史数据"""
        try:
            historical_data = self.db.get_historical_prices(
                symbol=symbol,
                market="US",
                frequency=frequency,
                start_date=start_date,
                end_date=end_date
            )
            
            logging.info(f"从数据库获取了 {symbol} 的 {len(historical_data)} 条历史数据 "
                        f"({start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')})")
            
            return historical_data
            
        except Exception as e:
            logging.error(f"从数据库获取历史数据失败 {symbol}: {e}")
            return []

    async def get_stock_info(self, symbol: str) -> dict:
        """获取股票基本信息"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            return {
                "symbol": symbol,
                "name": info.get("longName", info.get("shortName", "")),
                "exchange": info.get("exchange", ""),
                "currency": info.get("currency", "USD"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "description": info.get("longBusinessSummary", ""),
            }
        except Exception as e:
            logging.error(f"获取股票信息失败 {symbol}: {e}")
            return {}