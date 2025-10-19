import aiohttp
import asyncio
import requests
from typing import List, Optional
from datetime import datetime
import json
from websocket import WebSocketApp
import ssl
import threading

from .base_fetcher import BaseFetcher
from models.market_data import PriceData, MarketDataDB
from core.trading_hours import TradingHoursManager

class CryptoFetcher(BaseFetcher):
    """加密货币数据获取器"""
    
    def __init__(self, api_config: dict):
        super().__init__(api_config)
        self.trading_hours_manager = TradingHoursManager()
        self.db = MarketDataDB()
        self.websocket_thread = None
        self.is_websocket_running = False
    
    async def fetch_realtime_data(self, symbols: List[dict]) -> List[PriceData]:
        """获取加密货币实时数据"""
        results = []
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for symbol_info in symbols:
                # 加密货币24小时交易，不需要检查交易时间
                task = self._fetch_single_crypto(session, symbol_info)
                tasks.append(task)
            
            # 并行获取数据
            crypto_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in crypto_results:
                if isinstance(result, PriceData):
                    results.append(result)
                    # 保存到数据库
                    self.db.save_price_data(result)
        
        return results
    
    async def _fetch_single_crypto(self, session: aiohttp.ClientSession, 
                                 symbol_info: dict) -> Optional[PriceData]:
        """获取单个加密货币数据"""
        symbol = symbol_info['symbol']
        
        # 使用Binance REST API获取最新价格
        url = f"{self.api_config['binance']['base_url']}/api/v3/ticker/24hr"
        params = {'symbol': symbol.upper()}
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 创建PriceData对象
                    return PriceData(
                        symbol=symbol,
                        market=symbol_info.get('market', 'CRYPTO'),
                        timestamp=datetime.now(),
                        open=float(data.get('openPrice', 0)),
                        high=float(data.get('highPrice', 0)),
                        low=float(data.get('lowPrice', 0)),
                        close=float(data.get('lastPrice', 0)),
                        volume=float(data.get('volume', 0)),
                        frequency='1m'
                    )
                else:
                    print(f"Binance API错误: {response.status}")
                    return None
                    
        except Exception as e:
            print(f"获取加密货币数据失败 {symbol}: {e}")
            return None
    
    async def fetch_historical_data(self, symbol: str, frequency: str = '1d', 
                                  limit: int = 100) -> List[PriceData]:
        """获取加密货币历史数据"""
        # 将频率转换为Binance的间隔参数
        interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m',
            '1h': '1h', '4h': '4h', '1d': '1d', '1w': '1w'
        }
        
        interval = interval_map.get(frequency, '1d')
        url = f"{self.api_config['binance']['base_url']}/api/v3/klines"
        params = {
            'symbol': symbol.upper(),
            'interval': interval,
            'limit': limit
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        price_data_list = []
                        
                        for item in data:
                            price_data = PriceData(
                                symbol=symbol,
                                market='CRYPTO',
                                timestamp=datetime.fromtimestamp(item[0] / 1000),
                                open=float(item[1]),
                                high=float(item[2]),
                                low=float(item[3]),
                                close=float(item[4]),
                                volume=float(item[5]),
                                frequency=frequency
                            )
                            price_data_list.append(price_data)
                        
                        return price_data_list
                    else:
                        print(f"Binance历史数据API错误: {response.status}")
                        return []
                        
        except Exception as e:
            print(f"获取加密货币历史数据失败 {symbol}: {e}")
            return []
    
    def start_websocket_monitoring(self, symbols: List[dict], callback):
        """启动WebSocket监控"""
        self.is_websocket_running = True
        
        # 创建WebSocket URL
        streams = [f"{symbol['symbol'].lower()}@kline_1m" for symbol in symbols]
        combined_stream = "/".join(streams)
        ws_url = f"wss://stream.binance.com:9443/stream?streams={combined_stream}"
        
        def on_message(ws, message):
            """处理WebSocket消息"""
            if not self.is_websocket_running:
                return
                
            data = json.loads(message)
            kline = data['k']
            
            # 仅在K线收盘时处理
            if kline['x']:  # K线是否完结
                price_data = PriceData(
                    symbol=kline['s'],
                    market='CRYPTO',
                    timestamp=datetime.fromtimestamp(kline['t'] / 1000),
                    open=float(kline['o']),
                    high=float(kline['h']),
                    low=float(kline['l']),
                    close=float(kline['c']),
                    volume=float(kline['v']),
                    frequency='1m'
                )
                
                # 保存到数据库
                self.db.save_price_data(price_data)
                
                # 调用回调函数
                if callback:
                    callback(price_data)
        
        def on_error(ws, error):
            """处理WebSocket错误"""
            print(f"加密货币WebSocket错误: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            """WebSocket关闭"""
            print("加密货币WebSocket连接关闭")
        
        def run_websocket():
            """运行WebSocket"""
            ws = WebSocketApp(
                ws_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        
        # 在单独的线程中运行WebSocket
        self.websocket_thread = threading.Thread(target=run_websocket)
        self.websocket_thread.daemon = True
        self.websocket_thread.start()
        print("加密货币WebSocket监控已启动")
    
    def stop_websocket_monitoring(self):
        """停止WebSocket监控"""
        self.is_websocket_running = False
        if self.websocket_thread:
            self.websocket_thread.join(timeout=5)
        print("加密货币WebSocket监控已停止")