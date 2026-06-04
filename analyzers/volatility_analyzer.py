from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta
from models.market import PriceData, VolatilityAlert
from analyzers.threshold_manager import ThresholdManager
from storage.market_db import MarketDataDB


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
        """分析日频波动：current_data 对比 DB 中严格早于其 date 的最近一条收盘价。"""
        return self._analyze_period_volatility(
            current_data=current_data,
            frequency_label='daily',
            db_frequency='1d',
            lookback=timedelta(days=14),  # 跨周末/假期留余量
        )

    def analyze_weekly_volatility(self, current_data: PriceData) -> Optional[VolatilityAlert]:
        """分析周频波动：current_data 对比 DB 中严格早于其 date 的最近一条收盘价。"""
        return self._analyze_period_volatility(
            current_data=current_data,
            frequency_label='weekly',
            db_frequency='1w',
            lookback=timedelta(weeks=4),
        )

    def _analyze_period_volatility(
        self,
        current_data: PriceData,
        frequency_label: str,
        db_frequency: str,
        lookback: timedelta,
    ) -> Optional[VolatilityAlert]:
        """日/周频共用的波动判定。

        关键点：不能用 historical_data[-2] 作为「上一期」—— StorageConsumer
        与 VolatilityConsumer 是并行订阅线程，DB 里是否已含 current_data
        本身是非确定的。改为按 date 严格过滤出早于当前 bar 的所有行，取最后一条。
        """
        symbol = current_data.symbol
        market = current_data.market

        end_date = current_data.timestamp
        start_date = end_date - lookback

        try:
            historical_data = self.db.get_historical_prices(
                symbol=symbol,
                market=market,
                frequency=db_frequency,
                start_date=start_date,
                end_date=end_date,
            )

            current_date = current_data.timestamp.date()
            prior = [d for d in historical_data if d.timestamp.date() < current_date]
            if not prior:
                logging.warning(
                    f"{frequency_label}波动分析: {symbol} 缺少早于 {current_date} 的历史数据，跳过"
                )
                return None

            previous_data = prior[-1]
            change_percent = self.calculate_change_percent(
                current_data.close, previous_data.close
            )
            threshold = self.threshold_manager.get_threshold(
                symbol, frequency_label, market=market
            )
            logging.info(
                f"{frequency_label}波动分析: {symbol} 最新价: {current_data.close}, "
                f"对比({previous_data.timestamp.date()}): {previous_data.close}, "
                f"涨跌幅: {change_percent:.2f}%, 阈值: {threshold}%"
            )
            if abs(change_percent) >= threshold:
                return VolatilityAlert(
                    symbol=symbol,
                    name=symbol,
                    frequency=frequency_label,
                    current_change=change_percent,
                    threshold=threshold,
                    current_price=current_data.close,
                    previous_price=previous_data.close,
                    timestamp=datetime.now(),
                )
        except Exception as e:
            logging.error(f"分析{frequency_label}波动时出错 {symbol}: {e}", exc_info=True)

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
