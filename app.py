import asyncio
import logging
from datetime import datetime
from typing import List

from core.smart_scheduler import SmartScheduler
from core.fetchers.stock_fetcher import StockFetcher
from core.fetchers.crypto_fetcher import CryptoFetcher
from core.analyzers.volatility_analyzer import VolatilityAnalyzer
from core.notifiers.wechat_notifier import WeChatNotifier
from core.threshold_manager import ThresholdManager
from config.settings import API_CONFIG, MONITOR_CONFIG, TASK_CONFIG
from models.market_data import PriceData, VolatilityAlert, MarketDataDB

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class MarketMonitorApp:
    """市场监控应用"""
    
    def __init__(self):
        self.db = MarketDataDB()
        self.threshold_manager = ThresholdManager()
        self.wechat_notifier = WeChatNotifier()
        
        # 初始化数据获取器
        self.stock_fetcher = StockFetcher(API_CONFIG)
        self.crypto_fetcher = CryptoFetcher(API_CONFIG)
        
        # 初始化分析器
        self.volatility_analyzer = VolatilityAnalyzer(self.threshold_manager)
        
        # 初始化调度器
        self.scheduler = SmartScheduler()
        
        # 统计信息
        self.monitoring_stats = {
            'total_alerts': 0,
            'last_run': None,
            'successful_fetches': 0,
            'failed_fetches': 0
        }
    
    async def execute_minute_monitoring(self):
        """执行分钟级监控"""
        logging.info("开始执行分钟级监控...")
        self.monitoring_stats['last_run'] = datetime.now()
        
        alerts = []
        
        try:
            # 获取股票数据并分析
            stock_symbols = self._get_monitoring_symbols('minute', 'stocks')
            if stock_symbols:
                stock_data = await self.stock_fetcher.fetch_realtime_data(stock_symbols)
                self._update_stats(len(stock_data), len(stock_symbols))
                
                for data in stock_data:
                    alert = self.volatility_analyzer.analyze_minute_volatility(data)
                    if alert:
                        alerts.append(alert)
            
            # 获取加密货币数据并分析
            crypto_symbols = self._get_monitoring_symbols('minute', 'crypto')
            if crypto_symbols:
                crypto_data = await self.crypto_fetcher.fetch_realtime_data(crypto_symbols)
                self._update_stats(len(crypto_data), len(crypto_symbols))
                
                for data in crypto_data:
                    alert = self.volatility_analyzer.analyze_minute_volatility(data)
                    if alert:
                        alerts.append(alert)
            
            # 获取期货数据并分析
            futures_symbols = self._get_monitoring_symbols('minute', 'futures')
            if futures_symbols:
                futures_data = await self.stock_fetcher.fetch_realtime_data(futures_symbols)
                self._update_stats(len(futures_data), len(futures_symbols))
                
                for data in futures_data:
                    alert = self.volatility_analyzer.analyze_minute_volatility(data)
                    if alert:
                        alerts.append(alert)
            
            # 发送告警
            for alert in alerts:
                self.wechat_notifier.send_alert(alert)
                self.monitoring_stats['total_alerts'] += 1
            
            logging.info(f"分钟级监控完成，发现 {len(alerts)} 个告警")
            
        except Exception as e:
            logging.error(f"分钟级监控执行失败: {e}")
            self.monitoring_stats['failed_fetches'] += 1
    
    async def execute_daily_analysis(self):
        """执行日频分析"""
        logging.info("开始执行日频分析...")
        
        alerts = []
        
        try:
            # 分析股票日频波动
            stock_symbols = self._get_monitoring_symbols('daily', 'stocks')
            for symbol_info in stock_symbols:
                daily_alerts = self.volatility_analyzer.analyze_daily_volatility(
                    symbol_info['symbol'], symbol_info.get('market', '')
                )
                alerts.extend(daily_alerts)
            
            # 分析加密货币日频波动
            crypto_symbols = self._get_monitoring_symbols('daily', 'crypto')
            for symbol_info in crypto_symbols:
                daily_alerts = self.volatility_analyzer.analyze_daily_volatility(
                    symbol_info['symbol'], symbol_info.get('market', 'CRYPTO')
                )
                alerts.extend(daily_alerts)
            
            # 分析期货日频波动
            futures_symbols = self._get_monitoring_symbols('daily', 'futures')
            for symbol_info in futures_symbols:
                daily_alerts = self.volatility_analyzer.analyze_daily_volatility(
                    symbol_info['symbol'], symbol_info.get('market', 'FUT')
                )
                alerts.extend(daily_alerts)
            
            # 发送告警
            for alert in alerts:
                self.wechat_notifier.send_alert(alert)
            
            logging.info(f"日频分析完成，发现 {len(alerts)} 个告警")
            
        except Exception as e:
            logging.error(f"日频分析执行失败: {e}")
    
    async def execute_weekly_analysis(self):
        """执行周频分析"""
        logging.info("开始执行周频分析...")
        
        alerts = []
        
        try:
            # 分析股票周频波动
            stock_symbols = self._get_monitoring_symbols('weekly', 'stocks')
            for symbol_info in stock_symbols:
                weekly_alerts = self.volatility_analyzer.analyze_weekly_volatility(
                    symbol_info['symbol'], symbol_info.get('market', '')
                )
                alerts.extend(weekly_alerts)
            
            # 分析加密货币周频波动
            crypto_symbols = self._get_monitoring_symbols('weekly', 'crypto')
            for symbol_info in crypto_symbols:
                weekly_alerts = self.volatility_analyzer.analyze_weekly_volatility(
                    symbol_info['symbol'], symbol_info.get('market', 'CRYPTO')
                )
                alerts.extend(weekly_alerts)
            
            # 分析期货周频波动
            futures_symbols = self._get_monitoring_symbols('weekly', 'futures')
            for symbol_info in futures_symbols:
                weekly_alerts = self.volatility_analyzer.analyze_weekly_volatility(
                    symbol_info['symbol'], symbol_info.get('market', 'FUT')
                )
                alerts.extend(weekly_alerts)
            
            # 发送告警
            for alert in alerts:
                self.wechat_notifier.send_alert(alert)
            
            logging.info(f"周频分析完成，发现 {len(alerts)} 个告警")
            
        except Exception as e:
            logging.error(f"周频分析执行失败: {e}")
    
    def _get_monitoring_symbols(self, frequency: str, asset_type: str) -> List[dict]:
        """获取监控标的列表"""
        return MONITOR_CONFIG.get(frequency, {}).get(asset_type, [])
    
    def _update_stats(self, successful: int, total: int):
        """更新统计信息"""
        self.monitoring_stats['successful_fetches'] += successful
        if successful < total:
            self.monitoring_stats['failed_fetches'] += (total - successful)
    
    def setup_scheduling(self):
        """设置任务调度"""
        # 分钟级监控 - 股票、期货（在交易时间运行）
        self.scheduler.add_minute_task(
            task_name="minute_stock_futures_monitor",
            task_func=lambda: asyncio.create_task(self.execute_minute_monitoring()),
            market_types=['A_STOCK', 'HK_STOCK', 'US_STOCK', 'FUTURES'],
            interval=TASK_CONFIG['minute_interval']
        )
        
        # 分钟级监控 - 加密货币（24小时运行）
        self.scheduler.add_minute_task(
            task_name="minute_crypto_monitor", 
            task_func=lambda: asyncio.create_task(self.execute_minute_monitoring()),
            market_types=['CRYPTO'],
            interval=TASK_CONFIG['minute_interval']
        )
        
        # 日频分析
        self.scheduler.add_daily_task(
            task_name="daily_analysis",
            task_func=lambda: asyncio.create_task(self.execute_daily_analysis()),
            market_types=['A_STOCK', 'HK_STOCK', 'US_STOCK', 'FUTURES', 'CRYPTO'],
            time_str=TASK_CONFIG['daily_time']
        )
        
        # 周频分析
        self.scheduler.add_weekly_task(
            task_name="weekly_analysis",
            task_func=lambda: asyncio.create_task(self.execute_weekly_analysis()),
            market_types=['A_STOCK', 'HK_STOCK', 'US_STOCK', 'FUTURES', 'CRYPTO'],
            time_str=TASK_CONFIG['weekly_time']
        )
    
    def send_startup_message(self):
        """发送启动消息"""
        total_symbols = 0
        for frequency in MONITOR_CONFIG.values():
            for asset_type in frequency.values():
                total_symbols += len(asset_type)
        
        startup_message = (
            "🚀 市场波动监控系统启动成功\n"
            f"监控标的: {total_symbols} 个\n"
            f"监控频率: 分钟级/日频/周频\n"
            f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "系统已开始运行，将自动监控市场波动并发送告警。"
        )
        
        # 发送测试消息
        self.wechat_notifier._send_wecom_message(startup_message)
    
    def run(self):
        """运行应用"""
        logging.info("启动市场波动监控系统...")
        
        # 发送启动消息
        self.send_startup_message()
        
        # 设置任务调度
        self.setup_scheduling()
        
        # 启动加密货币WebSocket监控
        crypto_symbols = self._get_monitoring_symbols('minute', 'crypto')
        if crypto_symbols:
            self.crypto_fetcher.start_websocket_monitoring(
                crypto_symbols, 
                self._handle_crypto_websocket_data
            )
        
        try:
            # 启动调度器
            self.scheduler.start()
        except KeyboardInterrupt:
            logging.info("接收到停止信号，正在关闭...")
            self.shutdown()
    
    def _handle_crypto_websocket_data(self, price_data: PriceData):
        """处理加密货币WebSocket数据"""
        # 数据已经保存到数据库，这里可以进行实时分析
        alert = self.volatility_analyzer.analyze_minute_volatility(price_data)
        if alert:
            self.wechat_notifier.send_alert(alert)
            self.monitoring_stats['total_alerts'] += 1
    
    def shutdown(self):
        """关闭应用"""
        logging.info("正在关闭系统...")
        
        # 停止加密货币WebSocket
        self.crypto_fetcher.stop_websocket_monitoring()
        
        # 停止调度器
        self.scheduler.stop()
        
        # 发送关闭消息
        shutdown_message = (
            "🛑 市场波动监控系统已关闭\n"
            f"运行时长: 统计信息待实现\n"
            f"总告警数: {self.monitoring_stats['total_alerts']}\n"
            f"关闭时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        self.wechat_notifier._send_wecom_message(shutdown_message)
        logging.info("系统已关闭")

if __name__ == "__main__":
    app = MarketMonitorApp()
    app.run()