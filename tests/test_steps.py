"""steps 核心抽象与管道编排测试。"""

import asyncio
import pytest

from steps.base import Step, Chain, Fork, FetchMultiSource, Task, TaskRunner


# ── 测试用 Step 实现（契约：list 进 list 出，空 list 终止链路）──

class AddStep(Step):
    def __init__(self, n: int):
        self.n = n

    async def process(self, items):
        return [x + self.n for x in items]


class MultiplyStep(Step):
    def __init__(self, n: int):
        self.n = n

    async def process(self, items):
        return [x * self.n for x in items]


class EmptyStep(Step):
    async def process(self, items):
        return []


class CollectorStep(Step):
    def __init__(self):
        self.received = []

    async def process(self, items):
        self.received.append(items)
        return items


class FailStep(Step):
    async def process(self, items):
        raise ValueError("boom")


class FetchStep(Step):
    def __init__(self, value: list):
        self.value = value

    async def process(self, items=()):
        return self.value


# ── Chain / pipe 测试 ──

class TestChain:
    def test_pipe_creates_chain(self):
        chain = AddStep(1) | AddStep(2)
        assert isinstance(chain, Chain)
        assert len(chain.steps) == 2

    def test_pipe_flattens(self):
        chain = AddStep(1) | AddStep(2) | AddStep(3)
        assert isinstance(chain, Chain)
        assert len(chain.steps) == 3

    def test_pipe_three_steps(self):
        chain = AddStep(1) | MultiplyStep(2) | AddStep(3)
        result = asyncio.run(chain.process([0]))
        # (0 + 1) * 2 + 3 = 5
        assert result == [5]

    def test_pipe_two_steps(self):
        chain = AddStep(10) | MultiplyStep(3)
        result = asyncio.run(chain.process([5]))
        # (5 + 10) * 3 = 45
        assert result == [45]

    def test_chain_stops_on_empty(self):
        collector = CollectorStep()
        chain = AddStep(1) | EmptyStep() | collector
        result = asyncio.run(chain.process([0]))
        assert result == []
        assert collector.received == []

    def test_single_step_pipe(self):
        chain = AddStep(5) | MultiplyStep(2)
        assert len(chain.steps) == 2

    def test_nested_chain_pipe(self):
        inner = AddStep(1) | AddStep(2)
        outer = inner | MultiplyStep(3)
        assert isinstance(outer, Chain)
        assert len(outer.steps) == 3
        result = asyncio.run(outer.process([0]))
        # (0 + 1 + 2) * 3 = 9
        assert result == [9]


# ── Fork 测试 ──

class TestFork:
    def test_fork_sends_to_all_branches(self):
        c1 = CollectorStep()
        c2 = CollectorStep()
        fork = Fork(c1, c2)
        result = asyncio.run(fork.process(["data"]))
        assert result == []
        assert c1.received == [["data"]]
        assert c2.received == [["data"]]

    def test_fork_isolates_failures(self):
        c1 = CollectorStep()
        fork = Fork(FailStep(), c1)
        result = asyncio.run(fork.process(["data"]))
        assert result == []
        assert c1.received == [["data"]]

    def test_fork_in_chain_terminates(self):
        collector = CollectorStep()
        after = CollectorStep()
        chain = AddStep(1) | Fork(collector) | after
        result = asyncio.run(chain.process([0]))
        assert result == []
        assert collector.received == [[1]]
        assert after.received == []


# ── FetchMultiSource 测试 ──

class TestFetchMultiSource:
    def test_aggregates_results(self):
        fms = FetchMultiSource(FetchStep([1, 2]), FetchStep([3]))
        result = asyncio.run(fms.process([]))
        assert result == [1, 2, 3]

    def test_skips_empty_results(self):
        fms = FetchMultiSource(FetchStep([1]), FetchStep([]), FetchStep([2]))
        result = asyncio.run(fms.process([]))
        assert result == [1, 2]

    def test_empty_sources(self):
        fms = FetchMultiSource()
        result = asyncio.run(fms.process([]))
        assert result == []


# ── Task 测试 ──

class TestTask:
    def test_task_runs_chain(self):
        collector = CollectorStep()
        chain = FetchStep([42]) | collector
        task = Task(name="test", chain=chain)
        asyncio.run(task.run())
        assert collector.received == [[42]]

    def test_task_catches_errors(self):
        chain = FailStep()
        task = Task(name="fail_task", chain=chain)
        # 不应抛出异常
        asyncio.run(task.run())


# ── app.py 集成测试 ──

class TestAppIntegration:
    def test_build_tasks_price(self):
        from tasks import build_tasks
        tasks = build_tasks(["astock_daily"], run_immediately=False, ignore_schedule=True)
        assert len(tasks) == 1
        assert tasks[0].name == "astock_daily"
        step_names = [s.__class__.__name__ for s in tasks[0].chain.steps]
        assert step_names == ["FetchAStock", "StorageStep", "VolatilityStep", "VolatilityNotifyStep"]

    def test_build_tasks_social_independent(self):
        from tasks import build_tasks
        tasks = build_tasks(["x_briefing", "weibo_briefing"], run_immediately=False, ignore_schedule=True)
        names = sorted(t.name for t in tasks)
        assert names == ["weibo_briefing", "x_briefing"]

    def test_build_tasks_all_types(self):
        from tasks import build_tasks
        keys = ["crypto_daily", "x_briefing", "market_briefing", "morning_briefing"]
        tasks = build_tasks(keys, run_immediately=False, ignore_schedule=True)
        names = sorted(t.name for t in tasks)
        assert names == ["crypto_daily", "market_briefing", "morning_briefing", "x_briefing"]

    def test_parse_args_default(self):
        from app import parse_args
        from tasks import DEFAULT_TASKS
        args = parse_args([])
        assert args.task_keys == DEFAULT_TASKS

    def test_parse_args_tasks(self):
        from app import parse_args
        args = parse_args(["-t", "astock_daily,crypto_daily"])
        assert args.task_keys == ["astock_daily", "crypto_daily"]

    def test_parse_args_dedup(self):
        from app import parse_args
        args = parse_args(["-t", "crypto_daily,crypto_daily"])
        assert args.task_keys == ["crypto_daily"]

    def test_parse_args_unknown_exits(self):
        from app import parse_args
        with pytest.raises(SystemExit):
            parse_args(["-t", "nonexistent_task"])

    def test_once_returns_without_waiting(self, monkeypatch):
        from app import TaskApp
        app = TaskApp()
        monkeypatch.setattr(app, "start", lambda *a, **k: None)

        def fail(*a, **k):
            raise AssertionError("should not keep running")

        monkeypatch.setattr("app.time.sleep", fail)
        app.run(["morning_briefing"], ignore_schedule=True)


class TestTaskRunner:
    def test_parallel_once_joins_before_return(self):
        done = []

        class Mark(Step):
            def __init__(self, name):
                self.name = name

            async def process(self, items):
                await asyncio.sleep(0.05)
                done.append(self.name)
                return items

        runner = TaskRunner()
        for name in ("a", "b"):
            runner.register(Task(
                name=name,
                chain=Mark(name),
                run_immediately=True,
                ignore_schedule=True,
            ))
        runner.start(sequential=False)
        assert sorted(done) == ["a", "b"]
