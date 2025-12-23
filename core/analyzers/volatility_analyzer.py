from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta
from models.market_data import PriceData, VolatilityAlert
from core.threshold_manager import ThresholdManager
from models.market_data import MarketDataDB


class VolatilityAnalyzer:
    """波动分析器"""
    
    def __init__(self, threshold_manager: ThresholdManager):
        self.threshold_manager = threshold_manager
        self.db = MarketDataDB()
        self.price_history = {}  # 用于存储价格历史
    
    def analyze_minute_volatility(self, current_data: PriceData) -> Optional[VolatilityAlert]:
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
                current_data.symbol, 'minute', market=current_data.market
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
    
    def analyze_daily_volatility(self, current_data: PriceData) -> Optional[VolatilityAlert]:
        """分析日频波动"""
        symbol = current_data.symbol
        market = current_data.market
        
        # 获取前一个交易日的数据
        end_date = datetime.fromisoformat(current_data.timestamp)
        start_date = end_date - timedelta(days=4)  # 多取一天确保有数据
        
        try:
            # 从数据库获取历史数据
            historical_data = self.db.get_historical_prices(
                symbol=symbol,
                market=market,
                frequency='1d',
                start_date=start_date,
                end_date=end_date
            )
            
            if len(historical_data) < 2:
                # 如果数据库中没有足够数据，返回None
                return None
            
            # 获取最新数据和前一个交易日数据
            latest_data = current_data
            previous_data = historical_data[-2]  # 前一个交易日
            
            change_percent = self.calculate_change_percent(
                latest_data.close, previous_data.close
            )
            
            threshold = self.threshold_manager.get_threshold(symbol, 'daily', market=current_data.market)
            logging.info(f"日频波动分析: {symbol} 最新价: {latest_data.close}, 前一日价: {previous_data.close}, "
                         f"涨跌幅: {change_percent:.2f}%, 阈值: {threshold}%")
            if abs(change_percent) >= threshold:
                return VolatilityAlert(
                    symbol=symbol,
                    name=symbol,
                    frequency='daily',
                    current_change=change_percent,
                    threshold=threshold,
                    current_price=latest_data.close,
                    previous_price=previous_data.close,
                    timestamp=datetime.now()
                )
                
        except Exception as e:
            logging.error(f"分析日频波动时出错 {symbol}: {e}")
            
        return None
    
    def analyze_weekly_volatility(self, current_data: PriceData) -> Optional[VolatilityAlert]:
        """分析周频波动"""
        symbol = current_data.symbol
        market = current_data.market
        
        # 获取前一周的数据
        end_date = current_data.timestamp
        start_date = end_date - timedelta(weeks=2)  # 多取一周确保有数据
        
        try:
            # 从数据库获取历史数据
            historical_data = self.db.get_historical_prices(
                symbol=symbol,
                market=market,
                frequency='1w',
                start_date=start_date,
                end_date=end_date
            )
            
            if len(historical_data) < 2:
                # 如果数据库中没有足够数据，返回None
                return None
            
            # 获取最新数据和前一周数据
            latest_data = current_data
            previous_data = historical_data[-2]  # 前一周
            
            change_percent = self.calculate_change_percent(
                latest_data.close, previous_data.close
            )
            
            threshold = self.threshold_manager.get_threshold(symbol, 'weekly', market=current_data.market)
            logging.info(f"周频波动分析: {symbol} 最新价: {latest_data.close}, 前一周价: {previous_data.close}, "   
                         f"涨跌幅: {change_percent:.2f}%, 阈值: {threshold}%")
            if abs(change_percent) >= threshold:
                return VolatilityAlert(
                    symbol=symbol,
                    name=symbol,
                    frequency='weekly',
                    current_change=change_percent,
                    threshold=threshold,
                    current_price=latest_data.close,
                    previous_price=previous_data.close,
                    timestamp=datetime.now()
                )
                
        except Exception as e:
            logging.error(f"分析周频波动时出错 {symbol}: {e}")
            
        return None
    
    def analyze_all_frequencies(self, current_data: PriceData) -> List[VolatilityAlert]:
        """分析所有频率的波动"""
        alerts = []
        
        # 分钟级波动分析
        minute_alert = self.analyze_minute_volatility(current_data)
        if minute_alert:
            alerts.append(minute_alert)
        
        # 日频波动分析
        daily_alert = self.analyze_daily_volatility(current_data)
        if daily_alert:
            alerts.append(daily_alert)
        
        # 周频波动分析
        weekly_alert = self.analyze_weekly_volatility(current_data)
        if weekly_alert:
            alerts.append(weekly_alert)
        
        return alerts
    
    def calculate_change_percent(self, current: float, previous: float) -> float:
        """计算涨跌幅"""
        if previous == 0:
            return 0.0
        return (current - previous) / previous * 100
