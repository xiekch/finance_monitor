import requests
import json
import logging
from typing import Optional
from models.market_data import VolatilityAlert
from config.settings import WECOM_CONFIG

class WeChatNotifier:
    """企业微信通知器"""
    
    def __init__(self):
        self.webhook_url = WECOM_CONFIG['webhook_url']
        self.session = requests.Session()
    
    def send_alert(self, alert: VolatilityAlert) -> bool:
        """发送波动告警"""
        message = self._format_alert_message(alert)
        return self._send_wecom_message(message, alert.frequency)
    
    def _format_alert_message(self, alert: VolatilityAlert) -> str:
        """格式化告警消息"""
        trend_icon = "📈" if alert.current_change > 0 else "📉"
        frequency_text = {
            'minute': '分钟级',
            'daily': '日级', 
            'weekly': '周级'
        }.get(alert.frequency, '波动')
        
        return (
            f"{trend_icon} 【{frequency_text}波动告警】\n"
            f"标的: {alert.name}({alert.symbol})\n"
            f"涨跌幅: {alert.current_change:+.2f}% (阈值: {alert.threshold}%)\n"
            f"当前价: {alert.current_price:.4f}\n"
            f"参考价: {alert.previous_price:.4f}\n"
            f"时间: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def _send_wecom_message(self, message: str, frequency: str = "minute") -> bool:
        """发送企业微信消息"""
        headers = {'Content-Type': 'application/json'}
        
        # 根据频率设置不同的消息格式
        data = {
            "msgtype": "text",
            "text": {
                "content": message
            }
        }
        
        try:
            response = self.session.post(
                self.webhook_url,
                headers=headers,
                data=json.dumps(data),
                timeout=10
            )
            
            if response.status_code == 200:
                logging.info(f"企业微信消息发送成功: {message[:50]}...")
                return True
            else:
                logging.error(f"企业微信消息发送失败: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"企业微信消息发送异常: {e}")
            return False
    
    def send_test_message(self) -> bool:
        """发送测试消息"""
        test_message = "🔔 市场波动监控系统测试\n系统启动成功，监控服务正常运行中..."
        return self._send_wecom_message(test_message)
    
    def send_summary_message(self, summary_data: dict) -> bool:
        """发送监控摘要消息"""
        message = "📊 【监控摘要报告】\n"
        message += f"统计时间: {summary_data.get('timestamp', 'N/A')}\n"
        message += f"监控标的数量: {summary_data.get('total_symbols', 0)}\n"
        message += f"发现告警数量: {summary_data.get('total_alerts', 0)}\n"
        message += f"数据获取成功率: {summary_data.get('success_rate', 0):.1f}%\n"
        
        if 'top_movers' in summary_data:
            message += "\n📈 主要波动:\n"
            for mover in summary_data['top_movers'][:5]:  # 显示前5个
                message += f"{mover['symbol']}: {mover['change']:+.2f}%\n"

        return self._send_wecom_message(message)

    def send_markdown(self, content: str, max_chars: int = 3500) -> bool:
        """发送任意 markdown 内容。超长按字符截断并附提示。"""
        if not content:
            logging.warning("[WeChatNotifier] send_markdown: 空内容，跳过发送")
            return False
        body = content
        if len(body) > max_chars:
            body = body[:max_chars] + "\n\n_（内容过长已截断，完整版见 SQLite briefings 表）_"
        headers = {"Content-Type": "application/json"}
        data = {"msgtype": "markdown", "markdown": {"content": body}}
        try:
            response = self.session.post(
                self.webhook_url, headers=headers, data=json.dumps(data), timeout=10,
            )
            if response.status_code == 200:
                logging.info(f"[WeChatNotifier] markdown 发送成功，长度={len(body)}")
                return True
            logging.error(
                f"[WeChatNotifier] markdown 发送失败: {response.status_code} - {response.text}"
            )
            return False
        except Exception as e:
            logging.error(f"[WeChatNotifier] markdown 发送异常: {e}")
            return False