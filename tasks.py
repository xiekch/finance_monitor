"""Task 注册表、复合组与构建逻辑。"""
from typing import Callable, Optional

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from steps.base import Step, Task, Fork
from steps.fetch import (
    FetchAStock,
    FetchUSStock,
    FetchCrypto,
    FetchFutures,
    FetchXPosts,
    FetchWeiboPosts,
    FetchMorningData,
)
from steps.notify import (
    VolatilityNotifyStep,
    BriefingNotifyStep,
    XBriefingNotifyStep,
    MorningBriefingNotifyStep,
    MarketBriefingNotifyStep,
    InvestmentNotifyStep,
)
from steps.investment_advice import AdviceStep
from steps.investment_review import ReviewStep
from steps.morning_ai import MorningAIStep
from steps.market_briefing import MarketBriefingStep
from steps.storage import StorageStep
from steps.volatility import VolatilityStep
from steps.ai_briefing import AIBriefingStep
from steps.publish_mp import PublishMPStep

from config.schedule import TASK_SCHEDULE

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


# ── Task 注册表 ──────────────────────────────────────────────
_PRICE_FETCH = {
    "astock": FetchAStock,
    "usstock": FetchUSStock,
    "crypto": FetchCrypto,
    "futures": FetchFutures,
}

TASK_REGISTRY: dict[str, Callable[[], Step]] = {
    **{
        f"{m}_{f}": (
            lambda m=m, f=f: _PRICE_FETCH[m](f) | StorageStep() | VolatilityStep() | VolatilityNotifyStep()
        )
        for m in _PRICE_FETCH
        for f in ("minute", "daily", "weekly")
    },
    "x_briefing": (
        lambda: FetchXPosts() | StorageStep() | AIBriefingStep()
        | Fork(StorageStep(), XBriefingNotifyStep())
    ),
    "weibo_briefing": (
        lambda: FetchWeiboPosts() | StorageStep() | AIBriefingStep() | Fork(StorageStep(), BriefingNotifyStep())
    ),
    "market_briefing": (
        lambda: FetchMorningData() | MarketBriefingStep() | MarketBriefingNotifyStep()
    ),
    "morning_briefing": (
        lambda: FetchXPosts() | StorageStep() | FetchMorningData()
        | MorningAIStep() | Fork(StorageStep(), MorningBriefingNotifyStep(), PublishMPStep())
    ),
    "investment_review_due": lambda: ReviewStep(kind="due") | InvestmentNotifyStep(),
    "investment_advice": lambda: AdviceStep() | InvestmentNotifyStep(),
    "investment_review_weekly": lambda: ReviewStep(kind="weekly") | InvestmentNotifyStep(),
    "investment_review_monthly": lambda: ReviewStep(kind="monthly") | InvestmentNotifyStep(),
}

TASK_KEYS: list[str] = list(TASK_REGISTRY)

# ── 复合 task 组（CLI 短名 → 多个子 task，保序展开）────────────────
TASK_GROUPS: dict[str, list[str]] = {
    "briefings": [
        "x_briefing",
        "market_briefing",
        "morning_briefing",
    ],
    "morning_pack": [
        "usstock_daily",
        "crypto_daily",
        "astock_daily",
        "futures_daily",
        "x_briefing",
        "market_briefing",
        "morning_briefing",
    ],
    "investment": [
        "investment_review_due",
        "investment_advice",
        "investment_review_weekly",
        "investment_review_monthly",
    ],
}

TASK_GROUP_KEYS: list[str] = list(TASK_GROUPS)
DEFAULT_TASKS: list[str] = TASK_GROUPS["briefings"]


def expand_task_keys(keys: list[str]) -> list[str]:
    """展开复合 task 组，返回去重后的 task 列表（保序）。"""
    if len(keys) == 1 and keys[0] in TASK_GROUPS:
        return list(TASK_GROUPS[keys[0]])

    expanded: list[str] = []
    for key in keys:
        if key in TASK_GROUPS:
            expanded.extend(TASK_GROUPS[key])
        else:
            expanded.append(key)

    seen: set[str] = set()
    deduped: list[str] = []
    for key in expanded:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def build_tasks(
    task_keys: list[str],
    run_immediately: bool = True,
    ignore_schedule: bool = False,
) -> list[Task]:
    tasks: list[Task] = []
    for key in task_keys:
        if key not in TASK_REGISTRY:
            continue
        tasks.append(Task(
            name=key,
            chain=TASK_REGISTRY[key](),
            trigger=build_trigger(TASK_SCHEDULE.get(key)),
            run_immediately=run_immediately,
            ignore_schedule=ignore_schedule,
        ))
    return tasks
