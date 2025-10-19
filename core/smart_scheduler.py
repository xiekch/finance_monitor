import schedule
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Callable, List
from .trading_hours import TradingHoursManager

class SmartScheduler:
    """智能调度器 - 只在交易时间运行"""
    
    def __init__(self):
        self.trading_hours_manager = TradingHoursManager()
        self.scheduled_tasks = {}
        self.is_running = False
    
    def add_minute_task(self, task_name: str, task_func: Callable, 
                       market_types: List[str], interval: int = 1):
        """添加分钟级任务（只在交易时间运行）"""
        def trading_time_wrapper():
            # 检查任一市场是否在交易中
            for market_type in market_types:
                if self.trading_hours_manager.is_trading_time(market_type):
                    task_func()
                    return
        
        # 使用schedule的every语法
        job = schedule.every(interval).minutes.do(trading_time_wrapper)
        self.scheduled_tasks[task_name] = job
    
    def add_daily_task(self, task_name: str, task_func: Callable, 
                      market_types: List[str], time_str: str = "16:00"):
        """添加日频任务"""
        def daily_wrapper():
            # 检查当天是否为任一市场的交易日
            for market_type in market_types:
                if self._is_trading_day(market_type):
                    task_func()
                    return
        
        job = schedule.every().day.at(time_str).do(daily_wrapper)
        self.scheduled_tasks[task_name] = job
    
    def add_weekly_task(self, task_name: str, task_func: Callable,
                       market_types: List[str], time_str: str = "09:00"):
        """添加周频任务"""
        def weekly_wrapper():
            for market_type in market_types:
                if self._is_trading_day(market_type):
                    task_func()
                    return
        
        job = schedule.every().monday.at(time_str).do(weekly_wrapper)
        self.scheduled_tasks[task_name] = job
    
    def _is_trading_day(self, market_type: str) -> bool:
        """检查是否为交易日"""
        now = datetime.now()
        config = self.trading_hours_manager.trading_hours[market_type]
        
        # 检查是否为假期
        date_str = now.strftime('%Y-%m-%d')
        if date_str in config.get('holidays', []):
            return False
        
        # 检查今天是否有交易时段
        for session in config['sessions']:
            if now.weekday() in session['days']:
                return True
        
        return False
    
    def start(self):
        """启动调度器"""
        self.is_running = True
        print("智能调度器启动...")
        
        while self.is_running:
            schedule.run_pending()
            time.sleep(30)  # 每30秒检查一次
    
    def stop(self):
        """停止调度器"""
        self.is_running = False
        schedule.clear()