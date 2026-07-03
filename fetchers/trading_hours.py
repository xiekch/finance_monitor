from datetime import datetime, time, timedelta
from typing import Dict, List
import pytz

class TradingHoursManager:
    """交易时间管理器"""
    
    def __init__(self):
        self.trading_hours = {
            # A股交易时间 (北京时间)
            'A_STOCK': {
                'timezone': 'Asia/Shanghai',
                'sessions': [
                    {
                        'start': time(9, 30),
                        'end': time(11, 30),
                        'days': [0, 1, 2, 3, 4]  # 周一至周五
                    },
                    {
                        'start': time(13, 0), 
                        'end': time(15, 0),
                        'days': [0, 1, 2, 3, 4]
                    }
                ],
                'holidays': [  # 2024年A股休市日示例
                    '2024-01-01', '2024-02-09', '2024-02-10', '2024-02-11',
                    '2024-02-12', '2024-02-13', '2024-02-14', '2024-04-04',
                    '2024-05-01', '2024-06-10', '2024-09-17', '2024-10-01',
                    '2024-10-02', '2024-10-03', '2024-10-04', '2024-10-07'
                ]
            },
            # 港股交易时间
            'HK_STOCK': {
                'timezone': 'Asia/Shanghai',
                'sessions': [
                    {
                        'start': time(9, 30),
                        'end': time(12, 0),
                        'days': [0, 1, 2, 3, 4]
                    },
                    {
                        'start': time(13, 0),
                        'end': time(16, 0), 
                        'days': [0, 1, 2, 3, 4]
                    }
                ],
                'holidays': []  # 实际需要配置港股假期
            },
            # 美股交易时间 (美东时间)
            'US_STOCK': {
                'timezone': 'America/New_York', 
                'sessions': [
                    {
                        'start': time(9, 30),
                        'end': time(16, 0),
                        'days': [0, 1, 2, 3, 4]
                    }
                ],
                'holidays': []  # 实际需要配置美股假期
            },
            # 加密货币 - 24小时交易
            'CRYPTO': {
                'timezone': 'UTC',
                'sessions': [
                    {
                        'start': time(0, 0),
                        'end': time(23, 59, 59),
                        'days': [0, 1, 2, 3, 4, 5, 6]  # 每天
                    }
                ],
                'holidays': []
            },
            # 期货交易时间 (示例)
            'FUTURES': {
                'timezone': 'Asia/Shanghai',
                'sessions': [
                    {
                        'start': time(9, 0),
                        'end': time(11, 30),
                        'days': [0, 1, 2, 3, 4]
                    },
                    {
                        'start': time(13, 30),
                        'end': time(15, 0),
                        'days': [0, 1, 2, 3, 4] 
                    },
                    {
                        'start': time(21, 0),
                        'end': time(2, 30),
                        'days': [0, 1, 2, 3, 4]  # 夜盘
                    }
                ],
                'holidays': []
            }
        }
    
    def is_trading_time(self, market_type: str, check_time: datetime = None) -> bool:
        """检查当前是否在交易时间内"""
        if check_time is None:
            check_time = datetime.now(pytz.UTC)
        
        if market_type not in self.trading_hours:
            return False
        
        config = self.trading_hours[market_type]
        timezone = pytz.timezone(config['timezone'])
        local_time = check_time.astimezone(timezone)
        
        # 检查是否为假期
        date_str = local_time.strftime('%Y-%m-%d')
        if date_str in config.get('holidays', []):
            return False
        
        # 检查是否为周末（如果不在session的days中）
        weekday = local_time.weekday()
        
        for session in config['sessions']:
            if weekday in session['days']:
                session_start = datetime.combine(local_time.date(), session['start']).astimezone(timezone)
                session_end = datetime.combine(local_time.date(), session['end']).astimezone(timezone)
                
                # 处理跨天的夜盘
                if session['end'] < session['start']:
                    session_end += timedelta(days=1)
                
                if session_start <= local_time <= session_end:
                    return True
        
        return False
    
    def get_next_trading_start(self, market_type: str) -> datetime:
        """获取下一个交易开始时间"""
        now = datetime.now(pytz.UTC)
        config = self.trading_hours[market_type]
        timezone = pytz.timezone(config['timezone'])
        
        # 检查今天剩余的交易时段
        local_now = now.astimezone(timezone)
        today = local_now.date()
        
        for session in config['sessions']:
            if local_now.weekday() in session['days']:
                session_start = datetime.combine(today, session['start']).astimezone(timezone)
                session_end = datetime.combine(today, session['end']).astimezone(timezone)
                
                # 处理跨天夜盘
                if session['end'] < session['start']:
                    session_end += timedelta(days=1)
                    if local_now < session_end:
                        return session_start
                else:
                    if local_now < session_start:
                        return session_start
                    elif local_now < session_end:
                        # 当前正在交易中，返回下一个交易时段
                        continue
        
        # 如果今天没有更多交易时段，找下个交易日的第一个时段
        for day_offset in range(1, 8):  # 最多检查7天
            next_day = today + timedelta(days=day_offset)
            next_day_weekday = next_day.weekday()
            
            for session in config['sessions']:
                if next_day_weekday in session['days']:
                    # 检查是否为假期
                    date_str = next_day.strftime('%Y-%m-%d')
                    if date_str not in config.get('holidays', []):
                        session_start = datetime.combine(next_day, session['start']).astimezone(timezone)
                        return session_start.astimezone(pytz.UTC)
        
        return now + timedelta(hours=24)  # 默认24小时后
    
    def get_market_type(self, symbol: str, market: str) -> str:
        """根据symbol和market获取市场类型"""
        if market in ['SH', 'SZ']:
            return 'A_STOCK'
        elif market == 'HK':
            return 'HK_STOCK'
        elif market in ['US', 'NASDAQ', 'NYSE']:
            return 'US_STOCK'
        elif market == 'FUT':
            return 'FUTURES'
        elif 'USDT' in symbol or 'BTC' in symbol:
            return 'CRYPTO'
        else:
            return 'A_STOCK'  # 默认