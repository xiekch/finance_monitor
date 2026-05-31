import logging
import signal
import sys
from datetime import datetime
import time
import asyncio
import os
from typing import Optional

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from producers.astock_producer import AStockProducer
from producers.usstock_producer import USStockProducer
from producers.crypto_producer import CryptoProducer
from producers.x_briefing_producer import XBriefingProducer
from consumers.volatility_consumer import VolatilityConsumer
from consumers.notification_consumer import NotificationConsumer
from consumers.storage_consumer import StorageConsumer
from consumers.ai_briefing_consumer import AIBriefingConsumer
from infra.message_queue import mq
from models.messages import MessageType, SystemEventMessage
from config.settings import PRODUCER_SCHEDULE
from config.social import SOCIAL_CONFIG, assert_social_env_ready


# (producer_cls, 构造时附加的 kwargs)；trigger 由 PRODUCER_SCHEDULE 单独提供
PRODUCER_REGISTRY: dict[str, tuple[type, dict]] = {
    "astock_minute":  (AStockProducer,  {"frequency": "minute"}),
    "astock_daily":   (AStockProducer,  {"frequency": "daily"}),
    "astock_weekly":  (AStockProducer,  {"frequency": "weekly"}),
    "usstock_minute": (USStockProducer, {"frequency": "minute"}),
    "usstock_daily":  (USStockProducer, {"frequency": "daily"}),
    "usstock_weekly": (USStockProducer, {"frequency": "weekly"}),
    "crypto_minute":  (CryptoProducer,  {"frequency": "minute"}),
    "crypto_daily":   (CryptoProducer,  {"frequency": "daily"}),
    "crypto_weekly":  (CryptoProducer,  {"frequency": "weekly"}),
    "x_briefing":     (XBriefingProducer, {}),
}

DEFAULT_PRODUCERS: list[str] = ["usstock_daily", "crypto_daily"]


_TRIGGER_TYPES = {
    "cron": CronTrigger,
    "interval": IntervalTrigger,
}


def build_trigger(spec: Optional[dict]) -> Optional[BaseTrigger]:
    """根据配置构造 APScheduler 触发器。spec=None 表示无调度。"""
    if spec is None:
        return None
    try:
        trigger_cls = _TRIGGER_TYPES[spec["type"]]
    except KeyError as e:
        raise ValueError(
            f"未知 trigger 类型: {spec.get('type')}; 可选: {sorted(_TRIGGER_TYPES)}"
        ) from e
    return trigger_cls(**spec.get("kwargs", {}))


class ProducerConsumerApp:
    """基于生产者-消费者模式的市场监控应用"""

    def __init__(self):
        self.producers = []
        self.consumers = []
        self.is_running = False

        # 配置日志
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("app.log", encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )

        # 后台启动Redis（推荐，不阻塞Python脚本）
        status = os.system("redis-server --daemonize yes")

        if status == 0:
            logging.info("Redis 启动命令执行成功（后台运行）")
        else:
            logging.error("Redis 启动失败，可能是命令不存在或权限问题")

    def setup_producers(
        self,
        producer_keys: list[str],
        run_immediately: bool = True,
        ignore_schedule: bool = False,
    ):
        """Instantiate producers selected by short key.

        触发器从 config.settings.PRODUCER_SCHEDULE 读取并注入；
        producer 类本身不再持有调度信息。

        Args:
            producer_keys: keys from PRODUCER_REGISTRY to enable.
            run_immediately: run once on startup.
            ignore_schedule: run only once, skip scheduling.
        """
        # 如果 x_briefing 在请求列表里但 SOCIAL_CONFIG.enabled=False，剔除并 warn
        if "x_briefing" in producer_keys and not SOCIAL_CONFIG["enabled"]:
            logging.warning(
                "[App] SOCIAL_CONFIG.enabled=False，已从启动列表中剔除 x_briefing"
            )
            producer_keys = [k for k in producer_keys if k != "x_briefing"]
        # 若 x_briefing 启用，做启动期 fail-fast 检查（缺 env / 空白名单）
        if "x_briefing" in producer_keys:
            assert_social_env_ready()

        for key in producer_keys:
            cls, extra_kwargs = PRODUCER_REGISTRY[key]
            trigger = build_trigger(PRODUCER_SCHEDULE.get(key))
            self.producers.append(cls(
                **extra_kwargs,
                trigger=trigger,
                run_immediately=run_immediately,
                ignore_schedule=ignore_schedule,
            ))

        logging.info(f"已启用 producer: {producer_keys}")
        print(f"生产者设置完成: {producer_keys}")

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

        # AI 简报消费者：仅在 SOCIAL_CONFIG.enabled=True 时启用
        if SOCIAL_CONFIG["enabled"]:
            self.consumers.append(AIBriefingConsumer())
            logging.info("[App] AIBriefingConsumer 已启用")
        else:
            logging.info("[App] SOCIAL_CONFIG.enabled=False，AIBriefingConsumer 跳过")

        print("消费者设置完成")

    def start_system(
        self,
        producer_keys: list[str],
        run_immediately: bool = True,
        ignore_schedule: bool = False,
    ):
        """启动系统

        Args:
            run_immediately: 是否在启动时立即执行一次生产任务
            ignore_schedule: 是否忽略调度，只执行一次
        """
        welcome_str = f"\n{'=' * 50}\n启动生产者-消费者模式市场监控系统\n{'=' * 50}"
        logging.info(welcome_str)

        print(f"运行模式: producers={producer_keys}, 立即执行={run_immediately}, 忽略调度={ignore_schedule}")

        self.is_running = True

        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # 设置生产者和消费者
        self.setup_producers(
            producer_keys=producer_keys,
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
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
            source="ProducerConsumerApp",
            payload={
                "event_type": "system_shutdown",
                "event_data": {
                    "timestamp": datetime.now().isoformat()
                }
            }
        )
        mq.publish(MessageType.SYSTEM_EVENT.value, shutdown_message.to_dict())

        os.system("redis-cli shutdown")
        logging.info("系统已完全停止")

    def run(
        self,
        producer_keys: list[str],
        run_immediately: bool = True,
        ignore_schedule: bool = False,
    ):
        """运行应用

        Args:
            run_immediately: 是否在启动时立即执行一次
            ignore_schedule: 是否忽略调度，只执行一次
        """
        try:
            self.start_system(
                producer_keys=producer_keys,
                run_immediately=run_immediately,
                ignore_schedule=ignore_schedule,
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


def parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description="市场监控系统")
    parser.add_argument(
        "--no-immediate", action="store_true", default=False, help="不立即执行生产任务"
    )
    parser.add_argument(
        "--once", action="store_true", default=False, help="只执行一次，忽略调度"
    )
    parser.add_argument(
        "-p", "--producers",
        type=str,
        default=None,
        help=f"逗号分隔的 producer 短名，可选: {sorted(PRODUCER_REGISTRY)}; 不传则使用默认 {DEFAULT_PRODUCERS}",
    )
    parser.add_argument(
        "--list-producers",
        action="store_true",
        default=False,
        help="列出所有可选 producer 后退出",
    )

    args = parser.parse_args(argv)

    if args.producers is None:
        args.producer_keys = list(DEFAULT_PRODUCERS)
    else:
        raw = [k.strip() for k in args.producers.split(",")]
        keys = [k for k in raw if k]
        if not keys:
            parser.error("--producers 不能为空")

        unknown = sorted(set(keys) - PRODUCER_REGISTRY.keys())
        if unknown:
            parser.error(
                f"未知 producer: {unknown}; 可选: {sorted(PRODUCER_REGISTRY)}"
            )

        seen = set()
        deduped = []
        for k in keys:
            if k in seen:
                continue
            seen.add(k)
            deduped.append(k)
        if len(deduped) != len(keys):
            logging.warning(f"producers 中存在重复 key，已去重: {keys} -> {deduped}")
        args.producer_keys = deduped

    return args


if __name__ == "__main__":
    args = parse_args()

    if args.list_producers:
        print("可选 producer:")
        for key, (cls, extra_kwargs) in PRODUCER_REGISTRY.items():
            extras = ", ".join(f"{k}={v!r}" for k, v in extra_kwargs.items())
            suffix = f" ({extras})" if extras else ""
            print(f"  {key:16s} -> {cls.__name__}{suffix}")
        sys.exit(0)

    app = ProducerConsumerApp()

    run_immediately = not args.no_immediate
    ignore_schedule = args.once

    app.run(
        producer_keys=args.producer_keys,
        run_immediately=run_immediately,
        ignore_schedule=ignore_schedule,
    )
