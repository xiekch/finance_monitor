import logging
import signal
import sys
import time

from steps.base import TaskRunner

from config.settings import WECOM_CONFIG
from config.social import assert_social_env_ready
from tasks import (
    TASK_KEYS,
    TASK_GROUPS,
    TASK_GROUP_KEYS,
    DEFAULT_TASKS,
    expand_task_keys,
    build_tasks,
)


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
        sequential: bool = True,
    ):
        welcome = f"\n{'=' * 50}\n启动 Task 编排市场监控系统\n{'=' * 50}"
        logging.info(welcome)
        print(
            f"运行模式: tasks={task_keys}, 立即执行={run_immediately}, "
            f"忽略调度={ignore_schedule}, 串行={sequential}"
        )

        check_weibo = "weibo_briefing" in task_keys
        if "x_briefing" in task_keys or check_weibo:
            assert_social_env_ready(check_weibo=check_weibo)

        self.is_running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        tasks = build_tasks(task_keys, run_immediately, ignore_schedule)
        for t in tasks:
            self.runner.register(t)

        self.runner.start(
            sequential=sequential and run_immediately,
        )

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
        sequential: bool = True,
    ):
        try:
            self.start(task_keys, run_immediately, ignore_schedule, sequential)

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
        "--parallel", action="store_true", default=False,
        help="立即执行时并行运行多个 task（默认按 task 列表顺序串行）",
    )
    parser.add_argument(
        "-t", "--tasks",
        type=str,
        default=None,
        dest="tasks_arg",
        help="逗号分隔的 task 短名或复合组名；不传则使用默认 briefings 组",
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
    args = parser.parse_args(argv)

    raw_input = args.tasks_arg
    if raw_input is None:
        args.task_keys = list(DEFAULT_TASKS)
    else:
        raw = [k.strip() for k in raw_input.split(",")]
        keys = [k for k in raw if k]
        if not keys:
            parser.error("--tasks 不能为空")

        valid = set(TASK_KEYS) | set(TASK_GROUP_KEYS)
        unknown = sorted(set(keys) - valid)
        if unknown:
            parser.error(
                f"未知 task: {unknown}; 可选 task: {sorted(TASK_KEYS)}; "
                f"复合组: {sorted(TASK_GROUP_KEYS)}"
            )

        args.task_keys = expand_task_keys(keys)

    return args


if __name__ == "__main__":
    args = parse_args()

    if args.list_tasks:
        print("可选 task:")
        for key in TASK_KEYS:
            print(f"  {key}")
        print("\n复合 task 组（展开为多个 task；立即执行默认串行，--parallel 可并行）:")
        for name, members in TASK_GROUPS.items():
            print(f"  {name} -> {', '.join(members)}")
        sys.exit(0)

    if args.webhook:
        WECOM_CONFIG['webhook_urls'] = args.webhook

    app = TaskApp()
    app.run(
        task_keys=args.task_keys,
        run_immediately=not args.no_immediate,
        ignore_schedule=args.once,
        sequential=not args.parallel,
    )
