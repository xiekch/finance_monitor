from tasks import TASK_GROUPS, TASK_REGISTRY, expand_task_keys
from config.schedule import TASK_SCHEDULE


def test_investment_group_is_separate():
    keys = expand_task_keys(["investment"])
    assert keys == [
        "investment_review_due",
        "investment_advice",
        "investment_review_weekly",
        "investment_review_monthly",
    ]
    for key in keys:
        assert key in TASK_REGISTRY
        assert key not in TASK_GROUPS["briefings"]
        assert key not in TASK_GROUPS["morning_pack"]


def test_only_advice_is_sent_to_wechat(monkeypatch):
    from steps.base import Chain
    from steps.investment_review import ReviewStep
    from steps.notify.investment import InvestmentNotifyStep
    import tasks
    monkeypatch.setattr(tasks, "AdviceStep", lambda: ReviewStep.__new__(ReviewStep))
    monkeypatch.setattr(tasks, "ReviewStep", lambda kind: ReviewStep.__new__(ReviewStep))
    monkeypatch.setattr(tasks, "InvestmentNotifyStep", lambda: InvestmentNotifyStep.__new__(InvestmentNotifyStep))
    advice = TASK_REGISTRY["investment_advice"]()
    assert isinstance(advice, Chain) and isinstance(advice.steps[-1], InvestmentNotifyStep)
    for key in ("investment_review_due", "investment_review_weekly", "investment_review_monthly"):
        assert isinstance(TASK_REGISTRY[key](), ReviewStep)


def test_investment_crons():
    assert TASK_SCHEDULE["investment_review_due"]["kwargs"] == {"hour": 8, "minute": 20}
    assert TASK_SCHEDULE["investment_advice"]["kwargs"] == {"hour": 9, "minute": 0}
    assert TASK_SCHEDULE["investment_review_weekly"]["kwargs"] == {
        "day_of_week": "mon", "hour": 21, "minute": 0,
    }
    assert TASK_SCHEDULE["investment_review_monthly"]["kwargs"] == {
        "day": 1, "hour": 21, "minute": 10,
    }
