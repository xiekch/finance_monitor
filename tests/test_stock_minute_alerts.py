from datetime import datetime, timedelta

from analyzers.threshold_manager import ThresholdManager
from analyzers.volatility_analyzer import VolatilityAnalyzer
from clients.wechat_notifier import WeChatNotifier
from models.market import PriceData

T0 = datetime(2026, 11, 23, 10, 0, 0)


def _analyzer(window=1.5, day=3.0):
    manager = ThresholdManager()
    manager.reload_minute_targets([{
        "name": "贵州茅台", "symbol": "600519", "market": "SH", "frequency": "minute",
        "threshold": window, "prev_close_threshold": day,
    }])
    return VolatilityAnalyzer(manager)


def _bar(close, minutes, prev_close=1000.0, symbol="600519", market="SH"):
    return PriceData(
        symbol=symbol, market=market, timestamp=T0 + timedelta(minutes=minutes, milliseconds=300),
        open=close, high=close, low=close, close=close, prev_close=prev_close,
    )


def test_alert_vs_prev_close_and_only_once_per_level():
    a = _analyzer()
    assert a.analyze_minute_volatility(_bar(1020, 0)) == []          # +2%，未到 3%
    first = a.analyze_minute_volatility(_bar(1031, 5))               # +3.1%
    assert [(x.basis, round(x.current_change, 1), x.previous_price) for x in first] == [
        ("昨收", 3.1, 1000.0)]
    assert a.analyze_minute_volatility(_bar(1035, 10)) == []         # 还在同一档，不重复
    second = a.analyze_minute_volatility(_bar(1061, 15))             # +6.1%，进入下一档
    assert [x.basis for x in second] == ["昨收"]
    down = a.analyze_minute_volatility(_bar(960, 20))                # 反方向单独计
    assert [x.basis for x in down] == ["昨收"] and down[0].current_change < 0


def test_alert_vs_price_30_minutes_ago():
    a = _analyzer()
    prices = [1000, 1002, 1004, 1006, 1008, 1010]                    # 0~25 分钟，缓慢上涨
    for i, p in enumerate(prices):
        assert a.analyze_minute_volatility(_bar(p, i * 5)) == []
    # 30 分钟时 1016 相对 0 分钟的 1000 涨 1.6%；而相对上一次轮询只涨 0.6%
    alerts = a.analyze_minute_volatility(_bar(1016, 30))
    assert [(x.basis, x.previous_price) for x in alerts] == [("30分钟前", 1000)]
    assert round(alerts[0].current_change, 1) == 1.6


def test_window_alert_cools_down_for_one_window():
    a = _analyzer(day=50.0)  # 只看相对 30 分钟前
    for i in range(6):
        a.analyze_minute_volatility(_bar(1000, i * 5))
    assert len(a.analyze_minute_volatility(_bar(1016, 30))) == 1
    assert a.analyze_minute_volatility(_bar(1030, 35)) == []         # 冷却中
    assert a.analyze_minute_volatility(_bar(1030, 55)) == []         # 距上次告警 25 分钟：仍冷却
    # 冷却过了（60 分钟）；30 分钟前是 1030，现价 1060 涨 2.9%
    assert len(a.analyze_minute_volatility(_bar(1060, 60))) == 1


def test_no_window_alert_until_history_is_long_enough():
    a = _analyzer()
    assert a.analyze_minute_volatility(_bar(1000, 0)) == []
    assert a.analyze_minute_volatility(_bar(1020, 5)) == []          # 才 5 分钟，没有 30 分钟前的价格


def test_window_ignores_previous_day():
    a = _analyzer()
    a.analyze_minute_volatility(_bar(1000, -24 * 60))                # 昨天
    assert a.analyze_minute_volatility(_bar(1014, 0)) == []          # 不能拿昨天当 30 分钟前


def test_missing_prev_close_skips_day_check():
    a = _analyzer()
    assert a.analyze_minute_volatility(_bar(1100, 0, prev_close=None)) == []


def test_crypto_and_futures_keep_last_poll_logic():
    a = _analyzer()
    fut = lambda close: PriceData(  # noqa: E731
        symbol="AU0", market="FUT", timestamp=T0, open=close, high=close, low=close, close=close)
    assert a.analyze_minute_volatility(fut(500)) == []
    alerts = a.analyze_minute_volatility(fut(520))
    assert len(alerts) == 1 and alerts[0].basis == ""


def test_message_shows_basis():
    a = _analyzer()
    alert = a.analyze_minute_volatility(_bar(1031, 0))[0]
    text = WeChatNotifier(webhook_urls=["x"])._format_alert_message(alert)
    assert "参考价（昨收）: 1000.0000" in text and "贵州茅台(600519)" in text


def test_alerts_use_dedicated_webhook_when_configured(monkeypatch):
    import steps.notify.volatility as vol

    monkeypatch.setattr(vol, "ALERT_WEBHOOK_URLS", ["https://example.com/alert"])
    assert vol.VolatilityNotifyStep().notifier.webhook_urls == ["https://example.com/alert"]

    monkeypatch.setattr(vol, "ALERT_WEBHOOK_URLS", [])
    from config.settings import WECOM_CONFIG
    assert vol.VolatilityNotifyStep().notifier.webhook_urls == WECOM_CONFIG["webhook_urls"]
