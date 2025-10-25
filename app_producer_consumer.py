import logging
import signal
import sys
from datetime import datetime
import time
import asyncio

from core.producers.astock_producer import AStockProducer
from core.producers.usstock_producer import (
    USStockMinuteProducer,
    USStockDailyProducer,
    USStockWeeklyProducer,
)
from core.producers.crypto_producer import CryptoProducer
from core.consumers.volatility_consumer import VolatilityConsumer
from core.consumers.notification_consumer import NotificationConsumer
from core.consumers.storage_consumer import StorageConsumer
from core.message_queue import mq
from core.message_types import MessageType, SystemEventMessage


class ProducerConsumerApp:
    """基于生产者-消费者模式的市场监控应用"""

    def __init__(self):
        self.producers = []
        self.consumers = []
        self.is_running = False

        # 配置日志
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("app.log", encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )

    def setup_producers(
        self, run_immediately: bool = True, ignore_schedule: bool = False
    ):
        """设置生产者

        Args:
            run_immediately: 是否在启动时立即执行一次
            ignore_schedule: 是否忽略调度，只执行一次
        """
        # A股数据生产者
        # a_stock_producer = AStockProducer(run_immediately=run_immediately, ignore_schedule=ignore_schedule)
        # self.producers.append(a_stock_producer)

        # 美股数据生产者 - 分频率
        minute_producer = USStockMinuteProducer(
            interval_minutes=5,
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
        )
        # self.producers.append(minute_producer)

        daily_producer = USStockDailyProducer(
            run_immediately=run_immediately, ignore_schedule=ignore_schedule
        )
        self.producers.append(daily_producer)

        weekly_producer = USStockWeeklyProducer(
            run_immediately=run_immediately, ignore_schedule=ignore_schedule
        )
        # self.producers.append(weekly_producer)

        # 加密货币数据生产者
        # crypto_producer = CryptoProducer(run_immediately=run_immediately, ignore_schedule=ignore_schedule)
        # self.producers.append(crypto_producer)

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

    def start_system(self, run_immediately: bool = True, ignore_schedule: bool = False):
        """启动系统

        Args:
            run_immediately: 是否在启动时立即执行一次生产任务
            ignore_schedule: 是否忽略调度，只执行一次
        """
        welcome_str = f"\n{'=' * 50}\n启动生产者-消费者模式市场监控系统\n{'=' * 50}"
        logging.info(welcome_str)
        print(welcome_str)

        print(f"运行模式: 立即执行={run_immediately}, 忽略调度={ignore_schedule}")

        self.is_running = True

        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # 设置生产者和消费者
        self.setup_producers(
            run_immediately=run_immediately, ignore_schedule=ignore_schedule
        )
        self.setup_consumers()

        # 启动消费者
        for consumer in self.consumers:
            consumer.start_consumption()

        # 启动生产者
        for producer in self.producers:
            producer.start_production()

        # 发送系统启动事件
        startup_message = SystemEventMessage(
            payload={
                "event_type": "system_start",
                "event_data": {
                    "timestamp": datetime.now().isoformat(),
                    "producers": [p.producer_name for p in self.producers],
                    "consumers": [c.consumer_name for c in self.consumers],
                    "run_immediately": run_immediately,
                    "ignore_schedule": ignore_schedule,
                },
            },
            source="ProducerConsumerApp",
        )
        mq.publish(MessageType.SYSTEM_EVENT.value, startup_message.to_dict())

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
        mq.publish(MessageType.SYSTEM_EVENT.value, shutdown_message.to_dict())

        logging.info("系统已完全停止")

    def run(self, run_immediately: bool = True, ignore_schedule: bool = False):
        """运行应用

        Args:
            run_immediately: 是否在启动时立即执行一次
            ignore_schedule: 是否忽略调度，只执行一次
        """
        try:
            self.start_system(
                run_immediately=run_immediately, ignore_schedule=ignore_schedule
            )

            # 如果忽略调度，等待生产任务完成后自动停止
            if ignore_schedule:
                print("忽略调度模式，等待生产任务完成后自动停止...")

                # 运行异步等待
                async def wait_and_stop():
                    await asyncio.sleep(60)
                    print("生产任务完成，自动停止系统...")
                    self.stop_system()

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(wait_and_stop())
                loop.close()
            else:
                # 正常调度模式，保持运行直到接收到停止信号
                print("正常调度模式，系统持续运行中...")
                try:
                    # 保持主线程运行
                    while self.is_running:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\n用户请求停止系统...")

        except KeyboardInterrupt:
            print("\n用户请求停止系统...")
        except Exception as e:
            logging.error(f"系统运行异常: {e}")
        finally:
            self.stop_system()


if __name__ == "__main__":
    import argparse

    # 命令行参数解析
    parser = argparse.ArgumentParser(description="市场监控系统")
    parser.add_argument(
        "--no-immediate", action="store_true", default=False, help="不立即执行生产任务"
    )
    parser.add_argument(
        "--once", action="store_true", default=False, help="只执行一次，忽略调度"
    )

    args = parser.parse_args()

    app = ProducerConsumerApp()

    # 根据命令行参数设置运行模式
    run_immediately = not args.no_immediate
    ignore_schedule = args.once

    app.run(run_immediately=run_immediately, ignore_schedule=ignore_schedule)
