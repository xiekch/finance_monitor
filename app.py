import logging
import signal
import sys
import time
import os
from typing import Optional

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from steps.base import Step, Task, TaskRunner, Fork, FetchMultiSource
from steps.fetch_astock import FetchAStock
from steps.fetch_usstock import FetchUSStock
from steps.fetch_crypto import FetchCrypto
from steps.fetch_futures import FetchFutures
from steps.fetch_x_posts import FetchXPosts
from steps.fetch_weibo_posts import FetchWeiboPosts
from steps.fetch_market_briefing import FetchMarketBriefing
from steps.fetch_morning_briefing import FetchMorningBriefing
from steps.storage import StorageStep
from steps.volatility import VolatilityStep
from steps.ai_briefing import AIBriefingStep
from steps.notify import NotifyStep

from config.settings import PRODUCER_SCHEDULE, MQ_BACKEND, WECOM_CONFIG
from config.social import SOCIAL_CONFIG, assert_social_env_ready


_TRIGGER_TYPES = {
    "cron": CronTrigger,
    "interval": IntervalTrigger,
}


def build_trigger(spec: Optional[dict]) -> Optional[BaseTrigger]:
    if spec is None:
        return None
    try:
        trigger_cls = _TRIGGER_TYPES[spec["type"]]
    except KeyError as e:
        raise ValueError(
            f"未知 trigger 类型: {spec.get('type')}; 可选: {sorted(_TRIGGER_TYPES)}"
        ) from e
    return trigger_cls(**spec.get("kwargs", {}))


def _social_trigger() -> CronTrigger:
    return CronTrigger(
        hour=SOCIAL_CONFIG["cron_hours"],
        minute=SOCIAL_CONFIG.get("cron_minute", 0),
    )


def _build_price_task(
    market: str,
    frequency: str,
    run_immediately: bool,
    ignore_schedule: bool,
) -> Task:
    fetch_cls = {
        "astock": FetchAStock,
        "usstock": FetchUSStock,
        "crypto": FetchCrypto,
        "futures": FetchFutures,
    }[market]

    name = f"{market}_{frequency}"
    chain = fetch_cls(frequency) | StorageStep() | VolatilityStep() | NotifyStep()
    trigger = build_trigger(PRODUCER_SCHEDULE.get(name))

    return Task(
        name=name,
        chain=chain,
        trigger=trigger,
        run_immediately=run_immediately,
        ignore_schedule=ignore_schedule,
    )


def _build_social_briefing_task(
    fetchers: list[Step],
    run_immediately: bool,
    ignore_schedule: bool,
) -> Task:
    chain = (
        FetchMultiSource(*fetchers)
        | StorageStep()
        | AIBriefingStep()
        | Fork(StorageStep(), NotifyStep())
    )
    trigger = None if ignore_schedule else _social_trigger()

    return Task(
        name="social_briefing",
        chain=chain,
        trigger=trigger,
        run_immediately=run_immediately,
        ignore_schedule=ignore_schedule,
    )


def _build_market_briefing_task(
    run_immediately: bool,
    ignore_schedule: bool,
) -> Task:
    chain = FetchMarketBriefing() | NotifyStep()
    trigger = build_trigger(PRODUCER_SCHEDULE.get("market_briefing"))

    return Task(
        name="market_briefing",
        chain=chain,
        trigger=trigger,
        run_immediately=run_immediately,
        ignore_schedule=ignore_schedule,
    )


def _build_morning_briefing_task(
    run_immediately: bool,
    ignore_schedule: bool,
) -> Task:
    chain = FetchMorningBriefing() | Fork(StorageStep(), NotifyStep())
    trigger = build_trigger(PRODUCER_SCHEDULE.get("morning_briefing"))

    return Task(
        name="morning_briefing",
        chain=chain,
        trigger=trigger,
        run_immediately=run_immediately,
        ignore_schedule=ignore_schedule,
    )


# 所有可用的 task key；x_briefing / weibo_briefing 在构建时合并为 social_briefing
TASK_KEYS: list[str] = [
    "astock_minute", "astock_daily", "astock_weekly",
    "usstock_minute", "usstock_daily", "usstock_weekly",
    "crypto_minute", "crypto_daily", "crypto_weekly",
    "futures_minute", "futures_daily", "futures_weekly",
    "x_briefing", "weibo_briefing",
    "market_briefing", "morning_briefing",
]

DEFAULT_TASKS: list[str] = [
    "usstock_daily", "crypto_daily", "x_briefing", "market_briefing", "morning_briefing",
]


def build_tasks(
    task_keys: list[str],
    run_immediately: bool = True,
    ignore_schedule: bool = False,
) -> list[Task]:
    tasks: list[Task] = []

    # 价格类 task：market_frequency 形式
    price_markets = {"astock", "usstock", "crypto", "futures"}
    for key in task_keys:
        parts = key.rsplit("_", 1)
        if len(parts) == 2 and parts[0] in price_markets:
            market, freq = parts
            tasks.append(_build_price_task(market, freq, run_immediately, ignore_schedule))

    # 社交简报：x_briefing / weibo_briefing 合并
    social_fetchers: list[Step] = []
    if "x_briefing" in task_keys:
        social_fetchers.append(FetchXPosts())
    if "weibo_briefing" in task_keys:
        social_fetchers.append(FetchWeiboPosts())
    if social_fetchers:
        tasks.append(_build_social_briefing_task(social_fetchers, run_immediately, ignore_schedule))

    # 行情早报
    if "market_briefing" in task_keys:
        tasks.append(_build_market_briefing_task(run_immediately, ignore_schedule))

    # 公众号 AI 早报
    if "morning_briefing" in task_keys:
        tasks.append(_build_morning_briefing_task(run_immediately, ignore_schedule))

    return tasks


class TaskApp:

    def __init__(self):
        self.runner = TaskRunner()
        self.is_running = False

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("app.log", encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
            force=True,
        )

    def start(
        self,
        task_keys: list[str],
        run_immediately: bool = True,
        ignore_schedule: bool = False,
    ):
        welcome = f"\n{'=' * 50}\n启动 Task 编排市场监控系统\n{'=' * 50}"
        logging.info(welcome)
        print(f"运行模式: tasks={task_keys}, 立即执行={run_immediately}, 忽略调度={ignore_schedule}")

        # 社交 env 检查
        check_weibo = "weibo_briefing" in task_keys
        if "x_briefing" in task_keys or check_weibo:
            assert_social_env_ready(check_weibo=check_weibo)

        self.is_running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        tasks = build_tasks(task_keys, run_immediately, ignore_schedule)
        for t in tasks:
            self.runner.register(t)

        self.runner.start()

        task_names = [t.name for t in tasks]
        logging.info(f"已启动 Task: {task_names}")
        print(f"系统启动完成，已启动 {len(tasks)} 个 Task: {task_names}")
        print("按 Ctrl+C 停止系统")

    def _signal_handler(self, signum, frame):
        print(f"\n接收到信号 {signum}，正在关闭系统...")
        self.stop()
        sys.exit(0)

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.runner.stop()
        logging.info("系统已停止")

    def run(
        self,
        task_keys: list[str],
        run_immediately: bool = True,
        ignore_schedule: bool = False,
    ):
        try:
            self.start(task_keys, run_immediately, ignore_schedule)

            if ignore_schedule:
                print("忽略调度模式，Task 已立即执行一次；保持运行等待处理完成，按 Ctrl+C 退出。")
            else:
                print("正常调度模式，系统持续运行中，按 Ctrl+C 退出。")

            try:
                while self.is_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n用户请求停止系统...")
        except KeyboardInterrupt:
            print("\n用户请求停止系统...")
        except Exception as e:
            logging.error(f"系统运行异常: {e}")
        finally:
            self.stop()


def parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description="市场监控系统")
    parser.add_argument(
        "--no-immediate", action="store_true", default=False,
        help="不立即执行",
    )
    parser.add_argument(
        "--once", action="store_true", default=False,
        help="只执行一次，忽略调度",
    )
    parser.add_argument(
        "-t", "--tasks",
        type=str,
        default=None,
        dest="tasks_arg",
        help=f"逗号分隔的 task 短名，可选: {sorted(TASK_KEYS)}; 不传则使用默认 {DEFAULT_TASKS}",
    )
    # 保留 -p / --producers 作为别名兼容
    parser.add_argument(
        "-p", "--producers",
        type=str,
        default=None,
        dest="producers_arg",
        help="(兼容别名) 等同于 --tasks",
    )
    parser.add_argument(
        "--webhook",
        type=str,
        action="append",
        default=None,
        help="企微推送 webhook URL（可多次指定），覆盖环境变量 WECOM_WEBHOOK_URL",
    )
    parser.add_argument(
        "--list-tasks",
        action="store_true",
        default=False,
        help="列出所有可选 task 后退出",
    )
    # 兼容别名
    parser.add_argument(
        "--list-producers",
        action="store_true",
        default=False,
        dest="list_tasks",
    )

    args = parser.parse_args(argv)

    raw_input = args.tasks_arg or args.producers_arg
    if raw_input is None:
        args.task_keys = list(DEFAULT_TASKS)
    else:
        raw = [k.strip() for k in raw_input.split(",")]
        keys = [k for k in raw if k]
        if not keys:
            parser.error("--tasks 不能为空")

        valid = set(TASK_KEYS)
        unknown = sorted(set(keys) - valid)
        if unknown:
            parser.error(f"未知 task: {unknown}; 可选: {sorted(TASK_KEYS)}")

        seen = set()
        deduped = []
        for k in keys:
            if k in seen:
                continue
            seen.add(k)
            deduped.append(k)
        if len(deduped) != len(keys):
            logging.warning(f"tasks 中存在重复 key，已去重: {keys} -> {deduped}")
        args.task_keys = deduped

    return args


if __name__ == "__main__":
    args = parse_args()

    if args.list_tasks:
        print("可选 task:")
        for key in TASK_KEYS:
            print(f"  {key}")
        sys.exit(0)

    if args.webhook:
        WECOM_CONFIG['webhook_urls'] = args.webhook

    app = TaskApp()
    app.run(
        task_keys=args.task_keys,
        run_immediately=not args.no_immediate,
        ignore_schedule=args.once,
    )
