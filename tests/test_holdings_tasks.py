from config.schedule import TASK_SCHEDULE
from tasks import TASK_GROUPS, TASK_REGISTRY


def test_holdings_task_is_registered_outside_groups():
    assert "holdings_advice" in TASK_REGISTRY
    for keys in TASK_GROUPS.values():
        assert "holdings_advice" not in keys


def test_holdings_cron():
    assert TASK_SCHEDULE["holdings_advice"] == {"type": "cron", "kwargs": {"hour": 8, "minute": 40}}


def test_holdings_chain_ends_with_notify(monkeypatch):
    import tasks
    from steps.base import Chain
    from steps.holdings_advice import HoldingsAdviceStep
    from steps.notify.investment import HoldingsNotifyStep
    monkeypatch.setattr(tasks, "HoldingsAdviceStep",
                        lambda: HoldingsAdviceStep.__new__(HoldingsAdviceStep))
    monkeypatch.setattr(tasks, "HoldingsNotifyStep",
                        lambda: HoldingsNotifyStep.__new__(HoldingsNotifyStep))
    chain = TASK_REGISTRY["holdings_advice"]()
    assert isinstance(chain, Chain)
    assert isinstance(chain.steps[0], HoldingsAdviceStep)
    assert isinstance(chain.steps[-1], HoldingsNotifyStep)


def test_holdings_notify_uses_dedicated_webhook(monkeypatch):
    from steps.notify import investment
    monkeypatch.setattr(investment, "HOLDINGS_WEBHOOK_URLS", ["https://example.com/hook"])
    assert investment.HoldingsNotifyStep().notifier.webhook_urls == ["https://example.com/hook"]
