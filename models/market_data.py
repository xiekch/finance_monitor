import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json

@dataclass
class PriceData:
    symbol: str
    market: str
    timestamp: datetime
    open: float
    high: float  
    low: float
    close: float
    volume: float = 0
    frequency: str = '1m'
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'market': self.market, 
            'timestamp': self.timestamp.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'frequency': self.frequency
        }

@dataclass
class VolatilityAlert:
    """波动率预警类（完整版）"""
    
    symbol: str
    name: str
    frequency: str
    current_change: float
    threshold: float
    current_price: float
    previous_price: float
    timestamp: datetime
    volume: Optional[float] = None

class MarketDataDB:
    """市场数据数据库管理"""
    
    def __init__(self, db_path: str = "market_data.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建价格数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL DEFAULT 0,
                frequency TEXT DEFAULT '1m',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_symbol_timestamp 
            ON price_data(symbol, timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_market_frequency 
            ON price_data(market, frequency)
        ''')
        
        conn.commit()
        conn.close()
    
    def save_price_data(self, price_data: PriceData):
        """保存价格数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO price_data 
            (symbol, market, timestamp, open, high, low, close, volume, frequency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            price_data.symbol, price_data.market, price_data.timestamp,
            price_data.open, price_data.high, price_data.low, 
            price_data.close, price_data.volume, price_data.frequency
        ))
        
        conn.commit()
        conn.close()
    
    def get_latest_price(self, symbol: str, market: str, frequency: str = '1m') -> Optional[PriceData]:
        """获取最新价格数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, market, timestamp, open, high, low, close, volume, frequency
            FROM price_data 
            WHERE symbol = ? AND market = ? AND frequency = ?
            ORDER BY timestamp DESC 
            LIMIT 1
        ''', (symbol, market, frequency))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return PriceData(
                symbol=row[0], market=row[1], timestamp=datetime.fromisoformat(row[2]),
                open=row[3], high=row[4], low=row[5], close=row[6], 
                volume=row[7], frequency=row[8]
            )
        return None
    
    def get_historical_prices(self, symbol: str, market: str, frequency: str, 
                            start_date: datetime, end_date: datetime) -> List[PriceData]:
        """获取历史价格数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, market, timestamp, open, high, low, close, volume, frequency
            FROM price_data 
            WHERE symbol = ? AND market = ? AND frequency = ? 
            AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (symbol, market, frequency, start_date, end_date))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            PriceData(
                symbol=row[0], market=row[1], timestamp=datetime.fromisoformat(row[2]),
                open=row[3], high=row[4], low=row[5], close=row[6], 
                volume=row[7], frequency=row[8]
            ) for row in rows
        ]
    
    def get_price_change(self, symbol: str, market: str, frequency: str, 
                        periods: int = 1) -> Optional[float]:
        """计算价格变动百分比"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT close FROM price_data 
            WHERE symbol = ? AND market = ? AND frequency = ?
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (symbol, market, frequency, periods + 1))
        
        rows = cursor.fetchall()
        conn.close()
        
        if len(rows) >= 2:
            current_close = rows[0][0]
            previous_close = rows[1][0]
            if previous_close > 0:
                return (current_close - previous_close) / previous_close * 100
        return None