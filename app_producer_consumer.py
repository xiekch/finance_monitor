import logging
import signal
import sys
from datetime import datetime

from core.producers.astock_producer import AStockProducer
from core.producers.usstock_producer import USStockProducer
from core.producers.crypto_producer import CryptoProducer
from core.consumers.volatility_consumer import VolatilityConsumer
from core.consumers.notification_consumer import NotificationConsumer
from core.consumers.storage_consumer import StorageConsumer
from core.message_queue import mq
from core.message_types import SystemEventMessage

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class ProducerConsumerApp:
    """基于生产者-消费者模式的市场监控应用"""

    def __init__(self):
        self.producers = []
        self.consumers = []
        self.is_running = False

    def setup_producers(self):
        """设置生产者"""
        # A股数据生产者
        a_stock_producer = AStockProducer()
        self.producers.append(a_stock_producer)
        
        # 美股数据生产者  
        us_stock_producer = USStockProducer()
        self.producers.append(us_stock_producer)
        
        # 加密货币数据生产者
        crypto_producer = CryptoProducer()
        self.producers.append(crypto_producer)

        print("生产者设置完成")

    def setup_consumers(self):
        """设置消费者"""
        # 数据存储消费者
        storage_consumer = StorageConsumer()
        self.consumers.append(storage_consumer)

        # 波动分析消费者
        volatility_consumer = VolatilityConsumer()
        self.consumers.append(volatility_consumer)

        # 通知发送消费者
        notification_consumer = NotificationConsumer()
        self.consumers.append(notification_consumer)

        print("消费者设置完成")

    def start_system(self):
        """启动系统"""
        print("=" * 50)
        print("启动生产者-消费者模式市场监控系统")
        print("=" * 50)

        self.is_running = True

        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # 设置生产者和消费者
        self.setup_producers()
        self.setup_consumers()

        # 启动消费者
        for consumer in self.consumers:
            consumer.start_consumption()

        # 启动生产者
        for producer in self.producers:
            # if isinstance(producer, CryptoProducer):
            #     # 加密货币生产者使用WebSocket
            #     producer.start_websocket_production()
            # else:
            # 其他生产者使用轮询
            producer.start_production(interval=60)  # 60秒间隔

        # 发送系统启动事件
        startup_message = SystemEventMessage(
            event_type="system_start",
            event_data={
                "timestamp": datetime.now().isoformat(),
                "producers": [p.producer_name for p in self.producers],
                "consumers": [c.consumer_name for c in self.consumers],
            },
            source="ProducerConsumerApp",
        )
        mq.publish("channel_system_event", startup_message.to_dict())

        print("系统启动完成，所有生产者和消费者已开始运行")
        print("按 Ctrl+C 停止系统")

    def signal_handler(self, signum, frame):
        """信号处理函数"""
        print(f"\n接收到信号 {signum}，正在关闭系统...")
        self.stop_system()
        sys.exit(0)

    def stop_system(self):
        """停止系统"""
        if not self.is_running:
            return

        self.is_running = False

        # 停止生产者
        for producer in self.producers:
            producer.stop_production()

        # 停止消费者
        for consumer in self.consumers:
            consumer.stop_consumption()

        # 发送系统关闭事件
        shutdown_message = SystemEventMessage(
            event_type="system_shutdown",
            event_data={"timestamp": datetime.now().isoformat()},
            source="ProducerConsumerApp",
        )
        mq.publish("channel_system_event", shutdown_message.to_dict())

        print("系统已完全停止")

    def run(self):
        """运行应用"""
        try:
            self.start_system()

            # 保持主线程运行
            import time

            while self.is_running:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n用户请求停止系统...")
            self.stop_system()
        except Exception as e:
            logging.error(f"系统运行异常: {e}")
            self.stop_system()


if __name__ == "__main__":
    app = ProducerConsumerApp()
    app.run()
