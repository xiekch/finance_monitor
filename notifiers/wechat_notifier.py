import requests
import json
import logging
import time
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

    def send_text(
        self,
        content: str,
        max_bytes: int = 2000,
        inter_part_sleep: float = 1.5,
    ) -> bool:
        """发送 text 类型消息（msgtype=text）。

        企微 text 类型上限 2048 字节（中文 1 字 3 字节），URL 不会渲染为可点击。
        超长时按字节预算拆分依次推送，全量发完不截断（段数不设上限）。

        多段投递时序：企微网关不保证按到达顺序投递（实际观察过乱序），段间需要
        足够窗口撑开。当前 inter_part_sleep=1.5s + 单段首次失败立即重试 1 次
        （重试与下一段间也都保持该间隔）。任一段两次都失败即返回 False（已发段不回滚）。
        """
        if not content:
            logging.warning("[WeChatNotifier] send_text: 空内容，跳过发送")
            return False
        if len(content.encode("utf-8")) <= max_bytes:
            return self._post_text(content)

        parts = self._split_for_text(content, max_bytes=max_bytes)
        total = len(parts)
        all_ok = True
        for i, part in enumerate(parts, start=1):
            body = f"({i}/{total})\n{part}"
            ok = self._post_text(body)
            if not ok:
                logging.warning(
                    f"[WeChatNotifier] 分段 {i}/{total} 首发失败，{inter_part_sleep}s 后重试 1 次"
                )
                time.sleep(inter_part_sleep)
                ok = self._post_text(body)
                if not ok:
                    logging.error(
                        f"[WeChatNotifier] 分段 {i}/{total} 重试仍失败，已发段不回滚"
                    )
            all_ok = all_ok and ok
            if i < total:
                time.sleep(inter_part_sleep)
        return all_ok

    def _post_text(self, body: str) -> bool:
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

    def _split_for_text(self, content: str, max_bytes: int) -> list:
        """按字节预算把 content 切完，全量返回，段数不设上限。

        预留 ~12 字节给 `(i/N)\n` 头（N 最大可达 ~99）；优先在 `\n\n`、再 `\n` 处切，
        最后字节硬切（decode errors='ignore' 避免切中 utf-8 多字节字符）。
        """
        header_reserve = 12
        budget = max_bytes - header_reserve

        remaining = content
        parts = []
        while remaining:
            remaining_bytes = remaining.encode("utf-8")
            if len(remaining_bytes) <= budget:
                parts.append(remaining)
                break
            # 在 budget 字节窗口内找最靠后的换行边界（双换行优先）
            window = remaining_bytes[:budget].decode("utf-8", errors="ignore")
            split_at = window.rfind("\n\n")
            if split_at <= 0:
                split_at = window.rfind("\n")
            if split_at <= 0:
                split_at = len(window)  # 没有换行就硬切（字符边界由 decode 保证）
            parts.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        return parts

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
