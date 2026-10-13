import asyncio
import logging
from typing import List

from .base_fetcher import BaseFetcher
from models.market import PriceData
from storage.market_db import MarketDataDB
from fetchers.trading_hours import TradingHoursManager
from fetchers.sina_quote import fetch_sina_quotes, price_from_fields, sina_code


class FuturesFetcher(BaseFetcher):
    """期货数据获取器：实时走新浪，历史走 akshare"""

    def __init__(self, api_config: dict):
        super().__init__(api_config)
        self.trading_hours_manager = TradingHoursManager()
        self.db = MarketDataDB()

    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """交易时段走新浪期货连续报价；非交易时段用 DB 里的分钟线。"""
        results = []
        live = []
        for symbol_info in symbols:
            symbol = symbol_info['symbol']
            market = symbol_info.get('market', 'FUT')
            market_type = self.trading_hours_manager.get_market_type(symbol, market)
            if not self.trading_hours_manager.is_trading_time(market_type):
                latest = self.db.get_latest_price(symbol, market=market, frequency='1m')
                if latest:
                    logging.info(f"[FuturesFetcher] {symbol} 非交易时段，使用 DB 缓存")
                    results.append(latest)
                continue
            live.append(symbol_info)
        if live:
            results.extend(await self._fetch_sina_futures(live))
        return results

    async def _fetch_sina_futures(self, symbols: List[dict]) -> List[PriceData]:
        codes = [sina_code(info['symbol'], info.get('market', 'FUT')) for info in symbols]
        try:
            quotes = await fetch_sina_quotes(codes)
        except Exception as e:
            logging.error(f"[FuturesFetcher] 新浪行情获取失败: {e}")
            return []
        prices = []
        for info in symbols:
            code = sina_code(info['symbol'], info.get('market', 'FUT'))
            fields = quotes.get(code)
            if not fields:
                logging.error(f"[FuturesFetcher] 新浪未返回 {info.get('name', info['symbol'])}")
                continue
            price = price_from_fields(info['symbol'], info.get('market', 'FUT'), fields)
            if price is None:
                logging.error(f"[FuturesFetcher] 新浪报价无效 {info.get('name', info['symbol'])}")
                continue
            prices.append(price)
        logging.info(f"[FuturesFetcher] 新浪行情 {len(prices)}/{len(symbols)}")
        return prices

    async def fetch_historical_data(
        self,
        symbol: str,
        frequency: str = '1d',
        limit: int = 100,
        market: str = 'FUT',
    ) -> List[PriceData]:
        if frequency not in ('1d', '1w'):
            logging.error(f"[FuturesFetcher] 不支持的历史频率: {frequency}")
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_historical_sync, symbol, market, frequency, limit,
        )

    def _fetch_historical_sync(
        self, symbol: str, market: str, frequency: str, limit: int,
    ) -> List[PriceData]:
        try:
            import akshare as ak
            import pandas as pd
        except ImportError:
            logging.error("[FuturesFetcher] akshare/pandas 未安装")
            return []

        try:
            df = ak.futures_zh_daily_sina(symbol=symbol)
        except Exception as e:
            logging.error(f"[FuturesFetcher] akshare 拉取 {symbol} 失败: {e}")
            return []
        if df is None or df.empty:
            logging.warning(f"[FuturesFetcher] akshare {symbol} 返回空")
            return []

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()

        if frequency == '1w':
            df = df.resample('W-FRI').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum',
            }).dropna()

        df = df.tail(limit)
        return [
            PriceData(
                symbol=symbol,
                market=market,
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
