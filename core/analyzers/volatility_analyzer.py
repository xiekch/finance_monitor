from typing import List, Dict, Any
from datetime import datetime, timedelta
from models.market_data import PriceData, VolatilityAlert
from core.threshold_manager import ThresholdManager

class VolatilityAnalyzer:
    """波动分析器"""
    
    def __init__(self, threshold_manager: ThresholdManager):
        self.threshold_manager = threshold_manager
        self.price_history = {}  # 用于存储价格历史
    
    def analyze_minute_volatility(self, current_data: PriceData) -> VolatilityAlert:
        """分析分钟级波动"""
        symbol_key = f"{current_data.market}_{current_data.symbol}"
        
        # 获取历史价格
        if symbol_key in self.price_history:
            previous_data = self.price_history[symbol_key]
            change_percent = self.calculate_change_percent(
                current_data.close, previous_data.close
            )
            
            # 检查阈值
            threshold = self.threshold_manager.get_threshold(
                current_data.symbol, 'minute'
            )
            
            if abs(change_percent) >= threshold:
                return VolatilityAlert(
                    symbol=current_data.symbol,
                    name=current_data.symbol,  # 实际应该从配置获取名称
                    frequency='minute',
                    current_change=change_percent,
                    threshold=threshold,
                    current_price=current_data.close,
                    previous_price=previous_data.close,
                    timestamp=datetime.now()
                )
        
        # 更新历史价格
        self.price_history[symbol_key] = current_data
        return None
    
    def analyze_daily_volatility(self, historical_data: List[PriceData]) -> List[VolatilityAlert]:
        """分析日频波动"""
        alerts = []
        if len(historical_data) < 2:
            return alerts
        
        latest = historical_data[-1]
        previous = historical_data[-2]
        
        change_percent = self.calculate_change_percent(latest.close, previous.close)
        threshold = self.threshold_manager.get_threshold(latest.symbol, 'daily')
        
        if abs(change_percent) >= threshold:
            alerts.append(VolatilityAlert(
                symbol=latest.symbol,
                name=latest.symbol,
                frequency='daily', 
                current_change=change_percent,
                threshold=threshold,
                current_price=latest.close,
                previous_price=previous.close,
                timestamp=datetime.now()
            ))
        
        return alerts
    
    def calculate_change_percent(self, current: float, previous: float) -> float:
        """计算涨跌幅"""
        if previous == 0:
            return 0.0
        return (current - previous) / previous * 100