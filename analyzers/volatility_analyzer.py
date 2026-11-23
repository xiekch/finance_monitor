from collections import deque
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta
from config.minute_targets import MINUTE_STOCK_MARKETS, WINDOW_MINUTES
from models.market import PriceData, VolatilityAlert
from analyzers.threshold_manager import ThresholdManager
from storage.market_db import MarketDataDB

# 轮询有几百毫秒的抖动，正好 30 分钟前的那次轮询价也要能被选中
_WINDOW_TOLERANCE = timedelta(seconds=60)


class VolatilityAnalyzer:
    """波动分析器"""
    
    def __init__(self, threshold_manager: ThresholdManager):
        self.threshold_manager = threshold_manager
        self.db = MarketDataDB()
        self.price_history = {}  # 用于存储价格历史（加密货币、期货：上一次轮询价）
        # 以下三个只用于持仓股票盯盘，都在内存里，重启后清空
        self._window_history: Dict[str, deque] = {}   # key -> [(时间, 现价)]
        self._window_alerted: Dict[tuple, datetime] = {}  # (key, 方向) -> 上次相对窗口告警的时间
        self._day_levels: Dict[tuple, int] = {}       # (key, 日期, 方向) -> 已提醒到第几档
    
    def analyze_minute_volatility(self, current_data: PriceData) -> List[VolatilityAlert]:
        """分析分钟级波动。

        股票（持仓盯盘）：相对昨收、相对 WINDOW_MINUTES 分钟前，任一超阈值就告警。
        其它（加密货币、期货）：相对上一次轮询价。
        """
        if current_data.market in MINUTE_STOCK_MARKETS:
            return self._analyze_stock_minute(current_data)
        alert = self._analyze_vs_last_poll(current_data)
        return [alert] if alert else []

    def _analyze_vs_last_poll(self, current_data: PriceData) -> Optional[VolatilityAlert]:
        """相对上一次轮询价。触发告警时不更新参考价。"""
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
                    name=self.threshold_manager.get_name(
                        current_data.symbol, current_data.market
                    ),
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

    def _analyze_stock_minute(self, current_data: PriceData) -> List[VolatilityAlert]:
        symbol, market, now = current_data.symbol, current_data.market, current_data.timestamp
        key = f"{market}_{symbol}"
        alerts: List[VolatilityAlert] = []

        # 相对昨收：同一天同一方向，每多越过一个阈值倍数才再提醒一次（3% → 6% → 9%）
        prev_close = current_data.prev_close
        if prev_close and prev_close > 0:
            change = self.calculate_change_percent(current_data.close, prev_close)
            threshold = self.threshold_manager.get_threshold(symbol, 'prev_close', market=market)
            level = int(abs(change) // threshold) if threshold > 0 else 0
            level_key = (key, now.date(), change > 0)
            if level > self._day_levels.get(level_key, 0):
                self._day_levels[level_key] = level
                alerts.append(self._build_alert(
                    current_data, change, threshold, prev_close, '昨收'))
        else:
            logging.debug(f"{symbol} 没有昨收，跳过相对昨收的判断")

        # 相对 N 分钟前：滚动窗口；同一方向告警后冷却一个窗口，避免每 5 分钟重复推送
        reference = self._window_reference(key, current_data)
        if reference:
            change = self.calculate_change_percent(current_data.close, reference)
            threshold = self.threshold_manager.get_threshold(symbol, 'minute', market=market)
            cool_key = (key, change > 0)
            last = self._window_alerted.get(cool_key)
            cooled = last is None or now - last >= timedelta(minutes=WINDOW_MINUTES)
            if abs(change) >= threshold and cooled:
                self._window_alerted[cool_key] = now
                alerts.append(self._build_alert(
                    current_data, change, threshold, reference, f'{WINDOW_MINUTES}分钟前'))
        return alerts

    def _window_reference(self, key: str, current_data: PriceData) -> Optional[float]:
        """WINDOW_MINUTES 分钟前的价格：不晚于该时刻的最近一次轮询价。

        只用当天的轮询价（隔夜的变化交给「相对昨收」）；历史不够长时返回 None。
        返回后把本次价格记进去。
        """
        now = current_data.timestamp
        history = self._window_history.setdefault(key, deque())
        while history and history[0][0].date() != now.date():
            history.popleft()
        cutoff = now - timedelta(minutes=WINDOW_MINUTES) + _WINDOW_TOLERANCE
        while len(history) >= 2 and history[1][0] <= cutoff:
            history.popleft()
        reference = history[0][1] if history and history[0][0] <= cutoff else None
        history.append((now, current_data.close))
        return reference

    def _build_alert(
        self, current_data: PriceData, change: float, threshold: float,
        reference: float, basis: str,
    ) -> VolatilityAlert:
        return VolatilityAlert(
            symbol=current_data.symbol,
            name=self.threshold_manager.get_name(current_data.symbol, current_data.market),
            frequency='minute',
            current_change=change,
            threshold=threshold,
            current_price=current_data.close,
            previous_price=reference,
            timestamp=datetime.now(),
            basis=basis,
        )
    
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
                    name=self.threshold_manager.get_name(symbol, market),
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
        alerts.extend(self.analyze_minute_volatility(current_data))
        
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
