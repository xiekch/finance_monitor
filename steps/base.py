"""Task 编排核心抽象。

借鉴 LangChain LCEL 的 Runnable 风格，用 ``|`` 管道语法声明数据链路。

用法示例::

    task = Task(
        name="astock_daily",
        chain=FetchAStock("daily") | StorageStep(db) | VolatilityStep() | NotifyStep(notifier),
        trigger=CronTrigger(hour=9, minute=30),
    )
"""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional, Sequence

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR


class Step(ABC):
    """管道中的一个处理步骤。"""

    @abstractmethod
    async def process(self, data: Any) -> Any:
        """处理数据并返回结果给下一步。返回 None 则链路终止。"""

    def __or__(self, other: Step) -> Chain:
        left = self.steps if isinstance(self, Chain) else [self]
        right = other.steps if isinstance(other, Chain) else [other]
        return Chain(left + right)


class Chain(Step):
    """由 ``|`` 运算符自动组合的步骤序列。本身也是 Step，可嵌套。"""

    def __init__(self, steps: list[Step]):
        self.steps = steps

    async def process(self, data: Any) -> Any:
        for step in self.steps:
            data = await step.process(data)
            if data is None:
                break
        return data


class Fork(Step):
    """分叉：把同一份数据交给多个分支分别处理，然后终止主链。"""

    def __init__(self, *branches: Step):
        self.branches = branches

    async def process(self, data: Any) -> None:
        for branch in self.branches:
            try:
                await branch.process(data)
            except Exception as e:
                logging.error(f"[Fork] branch {branch.__class__.__name__} failed: {e}", exc_info=True)
        return None


class FetchMultiSource(Step):
    """聚合多个数据源的 fetch 结果。用于社交简报多平台聚合。"""

    def __init__(self, *fetchers: Step):
        self.fetchers = fetchers

    async def process(self, data: Any = None) -> list:
        results = []
        for f in self.fetchers:
            result = await f.process(data)
            if result:
                if isinstance(result, list):
                    results.extend(result)
                else:
                    results.append(result)
        return results


class Task:
    """一条完整的数据处理链路 + 调度配置。

    启动系统 = 启动一组 Task。
    """

    def __init__(
        self,
        name: str,
        chain: Step,
        trigger: Optional[BaseTrigger] = None,
        run_immediately: bool = False,
        ignore_schedule: bool = False,
    ):
        self.name = name
        self.chain = chain
        self.trigger = trigger
        self.run_immediately = run_immediately
        self.ignore_schedule = ignore_schedule

    async def run(self):
        start_time = datetime.now()
        logging.info(f"[Task:{self.name}] 开始执行")
        try:
            await self.chain.process(None)
        except Exception as e:
            logging.error(f"[Task:{self.name}] 执行失败: {e}", exc_info=True)
        else:
            duration = (datetime.now() - start_time).total_seconds()
            logging.info(f"[Task:{self.name}] 执行完成，耗时 {duration:.2f}s")


class TaskRunner:
    """应用级调度器：一个共享的 BackgroundScheduler 管理所有 Task。"""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self._setup_listeners()

    def _setup_listeners(self):
        def on_success(event):
            logging.info(f"[TaskRunner] job {event.job_id} 执行成功")

        def on_error(event):
            logging.error(f"[TaskRunner] job {event.job_id} 执行失败: {event.exception}")

        self.scheduler.add_listener(on_success, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(on_error, EVENT_JOB_ERROR)

    def register(self, task: Task):
        self.tasks[task.name] = task

    def _run_task_sync(self, task_name: str):
        task = self.tasks[task_name]
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(task.run())
        finally:
            loop.close()

    def start(self):
        self.is_running = True

        for name, task in self.tasks.items():
            if task.run_immediately:
                logging.info(f"[TaskRunner] 立即执行 {name}")
                thread = threading.Thread(
                    target=self._run_task_sync, args=(name,), daemon=True,
                )
                thread.start()

            if not task.ignore_schedule and task.trigger:
                self.scheduler.add_job(
                    self._run_task_sync,
                    trigger=task.trigger,
                    args=[name],
                    id=f"{name}_job",
                    name=f"Task: {name}",
                    max_instances=1,
                    replace_existing=True,
                )

        if any(
            not t.ignore_schedule and t.trigger for t in self.tasks.values()
        ):
            self.scheduler.start()
            logging.info("[TaskRunner] 调度器已启动")

        logging.info(f"[TaskRunner] 已注册 {len(self.tasks)} 个 Task")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.is_running = False
        logging.info("[TaskRunner] 已停止")
