import requests
import json
import logging
from models.market import VolatilityAlert
from config.settings import WECOM_CONFIG


class WeChatNotifier:
    """企业微信通知器"""

    def __init__(self):
        self.webhook_url = WECOM_CONFIG['webhook_url']
        self.session = requests.Session()

    def send_alert(self, alert: VolatilityAlert) -> bool:
        """发送波动告警"""
        return self.send_text(self._format_alert_message(alert))

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

    def send_text(self, content: str, max_bytes: int = 2000) -> bool:
        """发送 text 类型消息（msgtype=text）。

        企微 text 类型上限 2048 字节（中文 1 字 3 字节），按字节截断；
        URL 不会渲染为可点击。
        """
        if not content:
            logging.warning("[WeChatNotifier] send_text: 空内容，跳过发送")
            return False
        suffix = "\n\n（内容过长已截断，完整版见 SQLite briefings 表）"
        body_bytes = content.encode("utf-8")
        if len(body_bytes) > max_bytes:
            truncated = body_bytes[: max_bytes - len(suffix.encode("utf-8"))].decode("utf-8", errors="ignore")
            body = truncated + suffix
        else:
            body = content
        headers = {"Content-Type": "application/json"}
        data = {"msgtype": "text", "text": {"content": body}}
        try:
            response = self.session.post(
                self.webhook_url, headers=headers, data=json.dumps(data), timeout=10,
            )
            if response.status_code == 200:
                logging.info(f"[WeChatNotifier] text 发送成功，字节={len(body.encode('utf-8'))}")
                return True
            logging.error(
                f"[WeChatNotifier] text 发送失败: {response.status_code} - {response.text}"
            )
            return False
        except Exception as e:
            logging.error(f"[WeChatNotifier] text 发送异常: {e}")
            return False

    def send_markdown(self, content: str, max_chars: int = 3500) -> bool:
        """发送 markdown 类型消息。超长按字符截断并附提示。

        企微 markdown 渲染链接为可点击，但样式有限；当前 AI 简报走 send_text，
        此方法保留备用（如未来想恢复 markdown 推送或别处复用）。
        """
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
