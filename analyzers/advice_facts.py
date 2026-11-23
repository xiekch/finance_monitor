"""建议的价格事实：由日 K 算出，不靠模型。

只回答「发生了什么」：窗口内最高最低收盘、目标价和失效价有没有碰到、哪天碰到。
碰到之后算对还是算错，由建议里写好的观察条件和复盘提示词决定，这里不判断。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from fetchers.price_history import DATA_SOURCE, DailyBar
from models.advice import AdviceDoc

_REFERENCE_RANGE_SLACK = 0.005


@dataclass(frozen=True)
class WindowFacts:
    start: date
    end: date
    bars: List[DailyBar]
    high: DailyBar
    low: DailyBar
    last: DailyBar
    target_touch: Optional[DailyBar]
    stop_touch: Optional[DailyBar]


def window_facts(doc: AdviceDoc, bars: List[DailyBar], today: date) -> Optional[WindowFacts]:
    """窗口是建议创建日到 min(今天, 到期日)。窗口内没有交易日返回 None。"""
    if doc.created_at is None or doc.expiry_date is None or doc.reference_price is None:
        return None
    start, end = doc.created_at, min(today, doc.expiry_date)
    in_window = sorted((b for b in bars if start <= b.day <= end), key=lambda b: b.day)
    if not in_window:
        return None
    ref = doc.reference_price
    return WindowFacts(
        start=start,
        end=end,
        bars=in_window,
        high=max(in_window, key=lambda b: b.high),
        low=min(in_window, key=lambda b: b.low),
        last=in_window[-1],
        target_touch=_first_touch(in_window, doc.target_price, ref),
        stop_touch=_first_touch(in_window, doc.stop_price, ref),
    )


def _first_touch(bars: List[DailyBar], level: Optional[float], ref: float) -> Optional[DailyBar]:
    """价位在参考价上方就看最高价，下方就看最低价，盘中碰到即算。"""
    if level is None:
        return None
    for bar in bars:
        if (bar.high >= level) if level > ref else (bar.low <= level):
            return bar
    return None


def check_reference_price(price: float, bars: List[DailyBar], ref_date: date,
                          tolerance: float) -> Optional[str]:
    """参考价和 reference_date 当天日 K 对得上返回 None；对不上返回原因。

    收盘价偏差在 tolerance 内，或落在当天最高最低价区间内，都算对得上。
    当天没有日 K（接口缺数据）无法判断，也返回 None。
    """
    bar = next((b for b in bars if b.day == ref_date), None)
    if bar is None:
        return None
    if abs(price - bar.close) <= tolerance * bar.close:
        return None
    if bar.low * (1 - _REFERENCE_RANGE_SLACK) <= price <= bar.high * (1 + _REFERENCE_RANGE_SLACK):
        return None
    return (f"参考价 {fmt(price)} 与 {ref_date.isoformat()} 日 K 对不上"
            f"（收 {fmt(bar.close)}，区间 {fmt(bar.low)}–{fmt(bar.high)}）")


def fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def md(day: date) -> str:
    return f"{day.month}/{day.day}"


def _bar_text(bar: DailyBar) -> str:
    return f"开 {fmt(bar.open)} 高 {fmt(bar.high)} 低 {fmt(bar.low)} 收 {fmt(bar.close)}"


def _touch_clause(name: str, level: Optional[float], touch: Optional[DailyBar]) -> Optional[str]:
    if level is None:
        return None
    if touch is None:
        return f"{name}未碰到"
    return f"{name}{md(touch.day)}盘中碰到（{_bar_text(touch)}）"


def price_line(doc: AdviceDoc, facts: WindowFacts) -> str:
    """复盘「价格」行，整行由程序写，不采信模型给的数字。单行、不含链接。"""
    parts = [f"参考价 {fmt(doc.reference_price)}（{md(doc.reference_date)}）"
             if doc.reference_date else f"参考价 {fmt(doc.reference_price)}"]
    parts.append(f"目标价 {fmt(doc.target_price)}")
    if doc.stop_price is not None:
        parts.append(f"失效价 {fmt(doc.stop_price)}")
    head = "，".join(parts) + "。"
    window = (f"窗口 {md(facts.start)}–{md(facts.end)} 共 {len(facts.bars)} 个交易日，"
              f"最高 {fmt(facts.high.high)}（{md(facts.high.day)}），"
              f"最低 {fmt(facts.low.low)}（{md(facts.low.day)}），"
              f"最后收 {fmt(facts.last.close)}（{md(facts.last.day)}）。")
    clauses = [c for c in (
        _touch_clause("目标价", doc.target_price, facts.target_touch),
        _touch_clause("失效价", doc.stop_price, facts.stop_touch),
    ) if c]
    tail = "；".join(clauses) + "。" if clauses else ""
    return f"{head}{window}{tail}数据：{DATA_SOURCE}。"


def prompt_facts(doc: AdviceDoc, facts: WindowFacts) -> str:
    """给复盘提示词的事实块，比「价格」行详细：带逐日日 K 和触及后的收盘。"""
    lines = [
        f"数据来源：{DATA_SOURCE}，由程序取得。",
        f"窗口：{facts.start.isoformat()} 至 {facts.end.isoformat()}，共 {len(facts.bars)} 个交易日。",
        f"最高 {fmt(facts.high.high)}（{md(facts.high.day)}），最低 {fmt(facts.low.low)}（{md(facts.low.day)}），"
        f"最后收盘 {fmt(facts.last.close)}（{md(facts.last.day)}）。",
        _level_line("目标价", doc.target_price, doc.reference_price, facts.target_touch, facts),
    ]
    if doc.stop_price is not None:
        lines.append(_level_line("失效价", doc.stop_price, doc.reference_price, facts.stop_touch, facts))
    if (facts.target_touch and facts.stop_touch and facts.target_touch.day == facts.stop_touch.day):
        lines.append(f"目标价和失效价都在 {md(facts.stop_touch.day)} 被触及，日内先后无法从日 K 判断。")
    lines.append("逐日日 K：")
    lines.extend(f"{md(b.day)} {_bar_text(b)}" for b in facts.bars)
    return "\n".join(lines)


def _level_line(name: str, level: float, ref: float, touch: Optional[DailyBar],
                facts: WindowFacts) -> str:
    side = "高于" if level > ref else "低于"
    head = f"{name} {fmt(level)}（{side}参考价 {fmt(ref)}）："
    if touch is None:
        return head + "窗口内盘中没有碰到。"
    later = [b for b in facts.bars if b.day > touch.day][:2]
    after = "；之后两个交易日收盘 " + "、".join(f"{fmt(b.close)}（{md(b.day)}）" for b in later) if later else ""
    return head + f"{md(touch.day)}盘中碰到（{_bar_text(touch)}）{after}。"
