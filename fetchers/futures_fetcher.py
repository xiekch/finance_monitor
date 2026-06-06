import aiohttp
import asyncio
import logging
from typing import List, Optional
from datetime import datetime

from .base_fetcher import BaseFetcher
from models.market import PriceData
from storage.market_db import MarketDataDB
from infra.trading_hours import TradingHoursManager


class FuturesFetcher(BaseFetcher):
    """期货数据获取器：实时走 iTick，历史走 akshare"""

    def __init__(self, api_config: dict):
        super().__init__(api_config)
        self.trading_hours_manager = TradingHoursManager()
        self.db = MarketDataDB()

    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        results = []
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_single(session, s) for s in symbols]
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for result in fetched:
                if isinstance(result, PriceData):
                    results.append(result)
        return results

    async def _fetch_single(
        self, session: aiohttp.ClientSession, symbol_info: dict,
    ) -> Optional[PriceData]:
        symbol = symbol_info['symbol']
        market = symbol_info.get('market', 'FUT')

        market_type = self.trading_hours_manager.get_market_type(symbol, market)
        if not self.trading_hours_manager.is_trading_time(market_type):
            latest = self.db.get_latest_price(symbol, market=market, frequency='1m')
            if latest:
                logging.info(f"[FuturesFetcher] {symbol} 非交易时段，使用 DB 缓存")
                return latest
            return None

        url = f"{self.api_config['itick']['base_url']}/stock/kline"
        params = {'region': market, 'code': symbol, 'kType': '1'}
        headers = {
            'accept': 'application/json',
            'token': self.api_config['itick']['token'],
        }
        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'data' in data and len(data['data']) >= 1:
                        latest = data['data'][-1]
                        return PriceData(
                            symbol=symbol,
                            market=market,
                            timestamp=datetime.now(),
                            open=latest.get('open', 0),
                            high=latest.get('high', 0),
                            low=latest.get('low', 0),
                            close=latest.get('close', 0),
                            volume=latest.get('volume', 0),
                            frequency='1m',
                        )
                else:
                    logging.error(f"[FuturesFetcher] iTick API 错误: {response.status}")
        except Exception as e:
            logging.error(f"[FuturesFetcher] iTick 获取 {symbol} 失败: {e}")
        return None

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
