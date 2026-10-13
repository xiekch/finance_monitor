import yfinance as yf
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from .base_fetcher import BaseFetcher
from models.market import PriceData
from storage.market_db import MarketDataDB
from fetchers.trading_hours import TradingHoursManager
from utils.rate_limit import get_rate_limiter
import logging


class USStockYfFetcher(BaseFetcher):
    """使用 yfinance 获取美股/港股数据的获取器"""

    def __init__(self, api_config: dict = None):
        super().__init__(api_config or {})
        self.trading_hours_manager = TradingHoursManager()
        self.db = MarketDataDB()
        yf_cfg = (api_config or {}).get('yfinance', {})
        self._yf_limiter = get_rate_limiter(
            'yfinance', yf_cfg.get('min_interval_seconds', 15),
        )
        # 同一次早报里，实时批量下载的日线留给随后的昨收查询，避免每个标的再打一遍。
        self._daily_cache: Dict[str, List[PriceData]] = {}

    @staticmethod
    def to_yfinance_ticker(symbol: str, market: str = "US") -> str:
        """将监控配置中的 symbol 转为 yfinance ticker。"""
        if market == "HK":
            return f"{int(symbol):04d}.HK"
        return symbol

    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """获取美股/港股实时数据"""
        results = []

        yf_symbols = [
            symbol_info
            for symbol_info in symbols
            if symbol_info.get("market") in ["US", "NASDAQ", "NYSE", "HK", "JP", "KR"]
        ]

        if not yf_symbols:
            return results

        realtime_results = await self._fetch_yfinance_realtime(yf_symbols)
        for result in realtime_results:
            if isinstance(result, PriceData):
                results.append(result)
                logging.debug(f"result {result}")

        return results

    async def _fetch_yfinance_realtime(self, symbols: List[dict]) -> List[PriceData]:
        """一次下载全部标的的日线。逐个 Ticker.history 会把 Yahoo 打到限流。"""
        tickers = [
            self.to_yfinance_ticker(info["symbol"], info.get("market", "US"))
            for info in symbols
        ]
        await self._yf_limiter.acquire()
        try:
            frame = await asyncio.to_thread(self._download_daily, tickers)
        except Exception as e:
            logging.error(f"yfinance 批量行情获取失败: {e}")
            frame = None
        self._store_daily_cache(frame, symbols)
        prices = []
        for info in symbols:
            ticker = self.to_yfinance_ticker(info["symbol"], info.get("market", "US"))
            bars = self._daily_cache.get(ticker) or []
            if not bars:
                logging.error(f"yfinance 未返回数据 for {ticker}")
                continue
            last = bars[-1]
            prices.append(PriceData(
                symbol=info["symbol"],
                market=info.get("market", "US"),
                timestamp=datetime.now(),
                open=last.open,
                high=last.high,
                low=last.low,
                close=last.close,
                volume=last.volume,
                frequency="1m",
            ))
        got = {price.symbol for price in prices}
        missing = [info for info in symbols if info["symbol"] not in got]
        if missing:
            logging.warning(
                f"yfinance 缺少 {len(missing)} 个标的，改用新浪行情"
            )
            prices.extend(await self._fetch_sina_fallback(missing))
        logging.info(f"yfinance 批量行情 {len(prices)}/{len(symbols)}")
        return prices

    async def _fetch_sina_fallback(self, symbols: List[dict]) -> List[PriceData]:
        from fetchers.sina_quote import fetch_sina_quotes, overseas_quote, overseas_sina_code

        coded = []
        for info in symbols:
            code = overseas_sina_code(info["symbol"], info.get("market", "US"))
            if code is None:
                logging.error(f"新浪没有 {info.get('name', info['symbol'])} 的备用代码")
                continue
            coded.append((info, code))
        if not coded:
            return []
        try:
            quotes = await fetch_sina_quotes([code for _, code in coded])
        except Exception as e:
            logging.error(f"新浪备用行情获取失败: {e}")
            return []
        prices = []
        for info, code in coded:
            market = info.get("market", "US")
            parsed = overseas_quote(info["symbol"], market, quotes.get(code))
            if parsed is None:
                logging.error(f"新浪备用报价无效 {info.get('name', info['symbol'])}")
                continue
            price, prev_close = parsed
            prices.append(price)
            ticker = self.to_yfinance_ticker(info["symbol"], market)
            yesterday = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0,
            ) - timedelta(days=1)
            self._daily_cache[ticker] = [PriceData(
                symbol=info["symbol"],
                market=price.market,
                timestamp=yesterday,
                open=prev_close,
                high=prev_close,
                low=prev_close,
                close=prev_close,
                volume=0,
                frequency="1d",
            )]
        return prices

    @staticmethod
    def _download_daily(tickers: List[str]):
        return yf.download(
            tickers,
            period="1mo",
            interval="1d",
            group_by="ticker",
            threads=False,
            progress=False,
            auto_adjust=False,
        )

    def _store_daily_cache(self, frame, symbols: List[dict]) -> None:
        tickers = [
            self.to_yfinance_ticker(info["symbol"], info.get("market", "US"))
            for info in symbols
        ]
        by_ticker = split_download_frame(frame, tickers)
        info_by_ticker = {
            self.to_yfinance_ticker(info["symbol"], info.get("market", "US")): info
            for info in symbols
        }
        for ticker, history in by_ticker.items():
            info = info_by_ticker[ticker]
            bars = bars_from_history(
                history,
                symbol=info["symbol"],
                market=info.get("market", "US"),
                frequency="1d",
            )
            if bars:
                self._daily_cache[ticker] = bars

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
        end_date: Optional[datetime] = None,
        market: str = "US",
    ) -> List[PriceData]:
        """获取指定日期时间的股票历史数据

        Args:
            symbol: 股票代码
            frequency: 数据频率
            start_date: 开始日期时间
            end_date: 结束日期时间 (默认为当前时间)
            market: 市场（US / HK 等）
        """
        if end_date is None:
            end_date = datetime.now()

        if start_date is None:
            start_date = end_date - timedelta(days=30)

        yf_symbol = self.to_yfinance_ticker(symbol, market)
        cached = self._daily_cache.get(yf_symbol)
        if cached and frequency == "1d":
            start_naive = _naive(start_date)
            end_naive = _naive(end_date)
            return [
                bar for bar in cached
                if start_naive <= _naive(bar.timestamp) <= end_naive
            ]

        try:
            yf_interval = self._convert_frequency(frequency)

            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            await self._yf_limiter.acquire()
            ticker = yf.Ticker(yf_symbol)

            history = ticker.history(
                start=start_date,
                end=end_date,
                interval=yf_interval,
                auto_adjust=False
            )

            if history.empty:
                logging.warning(
                    f"yfinance 未返回指定时间段的历史数据 for {yf_symbol} "
                    f"({start_str} to {end_str})"
                )
                return self._get_historical_from_db(
                    symbol, frequency, start_date, end_date, market,
                )

            price_data_list = []
            for timestamp, row in history.iterrows():
                if row.isnull().any():
                    continue

                price_data = PriceData(
                    symbol=symbol,
                    market=market,
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

            logging.info(
                f"从 yfinance 获取了 {yf_symbol} 的 {len(price_data_list)} 条历史数据 "
                f"({start_str} 到 {end_str}, 频率: {frequency})"
            )

            return price_data_list

        except Exception as e:
            logging.error(f"yfinance 历史数据获取失败 {yf_symbol}: {e}")
            return self._get_historical_from_db(
                symbol, frequency, start_date, end_date, market,
            )

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
        self, symbol: str, frequency: str, start_date: datetime, end_date: datetime,
        market: str = "US",
    ) -> List[PriceData]:
        """从数据库获取指定时间范围的历史数据"""
        try:
            historical_data = self.db.get_historical_prices(
                symbol=symbol,
                market=market,
                frequency=frequency,
                start_date=start_date,
                end_date=end_date
            )

            logging.info(
                f"从数据库获取了 {symbol} 的 {len(historical_data)} 条历史数据 "
                f"({start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')})"
            )

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


def _naive(ts: datetime) -> datetime:
    if getattr(ts, "tzinfo", None) is not None:
        return ts.replace(tzinfo=None)
    return ts


def split_download_frame(frame, tickers: List[str]) -> Dict[str, object]:
    """把 yf.download 的宽表拆成每个 ticker 一张表。兼容单标的和两种 MultiIndex。"""
    import pandas as pd

    if frame is None or getattr(frame, "empty", True):
        return {}
    columns = frame.columns
    if isinstance(columns, pd.MultiIndex):
        level0 = set(columns.get_level_values(0))
        if any(ticker in level0 for ticker in tickers):
            return {
                ticker: frame[ticker].dropna(how="all")
                for ticker in tickers
                if ticker in level0
            }
        level1 = set(columns.get_level_values(1))
        if any(ticker in level1 for ticker in tickers):
            return {
                ticker: frame.xs(ticker, axis=1, level=1).dropna(how="all")
                for ticker in tickers
                if ticker in level1
            }
        return {}
    if len(tickers) == 1:
        return {tickers[0]: frame.dropna(how="all")}
    return {}


def bars_from_history(history, symbol: str, market: str, frequency: str) -> List[PriceData]:
    bars: List[PriceData] = []
    for timestamp, row in history.iterrows():
        if row.isnull().any():
            continue
        close = row.get("Close")
        if close is None or close != close:
            continue
        ts = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
        try:
            volume = float(row.get("Volume"))
        except (TypeError, ValueError):
            volume = 0
        bars.append(PriceData(
            symbol=symbol,
            market=market,
            timestamp=_naive(ts),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(close),
            volume=volume,
            frequency=frequency,
        ))
    return bars