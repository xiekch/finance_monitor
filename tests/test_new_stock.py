import asyncio
from datetime import date

import pandas as pd

from fetchers.new_stock_fetcher import listings_on
from models.market import NewStockListing
from steps.notify.new_stock import NewStockNotifyStep, format_new_stock_message
from tasks import TASK_REGISTRY
from config.schedule import TASK_SCHEDULE

TODAY = date(2026, 11, 23)


def _table():
    return pd.DataFrame([
        {   # 今天上市（Timestamp）
            "股票代码": "920067", "股票简称": "华晟智能", "交易所": "北京证券交易所",
            "板块": "北交所", "发行价格": 23.52, "发行市盈率": 13.88, "行业市盈率": 38.47,
            "发行总数": 1666.6667, "申购日期": "2026-11-11",
            "上市日期": pd.Timestamp("2026-11-23"),
        },
        {   # 今天上市（字符串日期，缺发行价）
            "股票代码": "688001", "股票简称": "测试科技", "交易所": "上海证券交易所",
            "板块": "科创板", "发行价格": float("nan"), "发行市盈率": None, "行业市盈率": None,
            "发行总数": None, "申购日期": pd.NaT, "上市日期": "2026-11-23",
        },
        {   # 别的日子上市
            "股票代码": "920309", "股票简称": "菊乐股份", "交易所": "北京证券交易所",
            "板块": "北交所", "发行价格": 31.92, "发行市盈率": 11.99, "行业市盈率": 19.4,
            "发行总数": 1175.0, "申购日期": "2026-11-04",
            "上市日期": pd.Timestamp("2026-11-17"),
        },
        {   # 还没排上市日
            "股票代码": "301661", "股票简称": "猎奇智能", "交易所": "深圳证券交易所",
            "板块": "非科创板", "发行价格": None, "发行市盈率": None, "行业市盈率": 36.92,
            "发行总数": 1375.0, "申购日期": "2026-11-26", "上市日期": pd.NaT,
        },
    ])


def test_listings_on_picks_only_today_sorted_by_symbol():
    result = listings_on(_table(), TODAY)
    assert [s.symbol for s in result] == ["688001", "920067"]
    first, second = result
    assert first.issue_price is None and first.subscribe_date is None
    assert first.exchange == "上交所"
    assert second.issue_price == 23.52
    assert second.subscribe_date == date(2026, 11, 11)


def test_listings_on_empty_or_none():
    assert listings_on(None, TODAY) == []
    assert listings_on(pd.DataFrame(), TODAY) == []
    assert listings_on(_table(), date(2026, 1, 1)) == []


def test_message_lists_every_stock_and_skips_missing_fields():
    text = format_new_stock_message(listings_on(_table(), TODAY))
    assert "共 2 只" in text
    assert "测试科技" in text and "688001" in text
    assert "华晟智能" in text and "发行价 23.52 元" in text
    assert "行业 38.47" in text


class _Notifier:
    def __init__(self):
        self.sent = []

    def send_markdown(self, content):
        self.sent.append(content)
        return True


def test_notify_sends_once_when_there_are_listings():
    notifier = _Notifier()
    items = listings_on(_table(), TODAY)
    asyncio.run(NewStockNotifyStep(notifier=notifier).process(items))
    assert len(notifier.sent) == 1
    assert "华晟智能" in notifier.sent[0]


def test_notify_silent_when_nothing_lists():
    notifier = _Notifier()
    asyncio.run(NewStockNotifyStep(notifier=notifier).process([]))
    assert notifier.sent == []


def test_task_is_registered_and_scheduled_at_nine():
    assert "new_stock_listing" in TASK_REGISTRY
    spec = TASK_SCHEDULE["new_stock_listing"]
    assert spec["type"] == "cron"
    assert spec["kwargs"] == {"hour": 9, "minute": 0}
    assert TASK_REGISTRY["new_stock_listing"]() is not None


def test_notifier_uses_dedicated_webhook_when_configured(monkeypatch):
    import steps.notify.new_stock as mod
    monkeypatch.setattr(mod, "NEW_STOCK_WEBHOOK_URLS", ["https://example.com/dedicated"])
    assert NewStockNotifyStep().notifier.webhook_urls == ["https://example.com/dedicated"]


def test_notifier_falls_back_to_default_webhook(monkeypatch):
    import steps.notify.new_stock as mod
    from config.settings import WECOM_CONFIG
    monkeypatch.setattr(mod, "NEW_STOCK_WEBHOOK_URLS", [])
    assert NewStockNotifyStep().notifier.webhook_urls == WECOM_CONFIG["webhook_urls"]
