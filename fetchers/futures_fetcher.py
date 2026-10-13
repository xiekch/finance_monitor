import asyncio
import logging
from datetime import date
from typing import List, Optional

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
        """新浪连续报价。收盘后仍是当日收盘价；没有报价时再用今天的分钟线。"""
        priced = await self._fetch_sina_futures(symbols) if symbols else []
        got = {(p.symbol, p.market) for p in priced}
        results = list(priced)
        for info in symbols:
            market = info.get('market', 'FUT')
            if (info['symbol'], market) in got:
                continue
            latest = self._today_minute(info['symbol'], market)
            if latest:
                logging.info(f"[FuturesFetcher] {info['symbol']} 新浪无报价，使用今天的分钟线")
                results.append(latest)
        return results

    def _today_minute(self, symbol: str, market: str) -> Optional[PriceData]:
        latest = self.db.get_latest_price(symbol, market=market, frequency='1m')
        if latest is None or latest.timestamp.date() != date.today():
            return None
        return latest

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
