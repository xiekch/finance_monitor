import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json

from models.market import PriceData, VolatilityAlert


class MarketDataDB:
    """市场数据数据库管理"""

    def __init__(self, db_path: str = "market_data.db"):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """初始化数据库表（添加联合唯一索引防止重复）"""
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

        # 索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_symbol_timestamp
            ON price_data(symbol, timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_market_frequency
            ON price_data(market, frequency)
        ''')

        # 联合唯一索引（核心！从数据库层面防止重复）
        # 确保 (symbol, market, frequency, timestamp) 组合唯一
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_price_data
            ON price_data(symbol, market, frequency, timestamp)
        ''')

        conn.commit()
        conn.close()

    def exists_price_data(self, price_data: PriceData) -> bool:
        """
        查询是否已存在相同条件的价格数据
        判断条件：symbol + market + frequency + timestamp 组合唯一
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 1 FROM price_data
            WHERE symbol = ? AND market = ? AND frequency = ? AND timestamp = ?
            LIMIT 1
        ''', (
            price_data.symbol,
            price_data.market,
            price_data.frequency,
            price_data.timestamp
        ))

        # 若查询到记录（fetchone()不为None），返回True，否则返回False
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def save_price_data(self, price_data: PriceData) -> bool:
        """
        保存价格数据（先判断是否存在，不存在才插入）
        返回值：True=保存成功，False=已存在无需保存
        """
        # 第一步：先查询是否已存在
        if self.exists_price_data(price_data):
            # 存在重复数据，无需保存
            return False

        # 第二步：不存在则执行插入
        try:
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
            return True

        except Exception as e:
            print(f"保存价格数据失败：{e}")
            return False

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
                symbol=row[0], market=row[1], timestamp=row[2],  # 无需fromisoformat，直接是datetime对象
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
                symbol=row[0], market=row[1], timestamp=row[2],
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
