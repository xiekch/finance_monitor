"""投资复盘：到期结案、周回溯、月回溯。每份文件单独调用模型，只追加不改写。"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional

from analyzers.advice_facts import WindowFacts, price_line, window_facts
from clients.llm_client.factory import build_investment_llm_client
from config.investment import ADVICE_ROOT, MAX_REVIEWS_PER_RUN
from fetchers import price_history
from models.advice import (
    REVIEW_KINDS,
    AdviceDoc,
    InvestmentMessage,
    commit_message,
    is_blank_lesson,
    replace_review_line,
    review_line,
)
from steps.base import Step
from steps.investment_parse import build_review_prompt
from storage.advice_git import AdviceCommitter
from storage.advice_store import AdviceStore, previous_month, previous_week


class ReviewStep(Step):
    def __init__(self, kind: str, store_root: Path = ADVICE_ROOT, llm=None, committer=None,
                 max_per_run: int = MAX_REVIEWS_PER_RUN,
                 today_fn: Callable[[], date] = date.today, bars_fn=None):
        if kind not in REVIEW_KINDS:
            raise ValueError(f"未知复盘种类：{kind}")
        self.kind = kind
        self.label = REVIEW_KINDS[kind]
        self.name = f"ReviewStep[{kind}]"
        self.store = AdviceStore(store_root)
        self.llm = llm or build_investment_llm_client()
        self.committer = committer or AdviceCommitter()
        self.max_per_run = max_per_run
        self.today_fn = today_fn
        # 运行时再取模块属性，测试里替换 fetch_daily_bars 才会生效
        self.bars_fn = bars_fn or price_history.fetch_daily_bars

    async def _price_facts(self, doc: AdviceDoc, today: date) -> Optional[WindowFacts]:
        """程序取日 K 算价格事实。不支持的品种、接口失败、窗口内没有交易日都返回 None。"""
        end = min(today, doc.expiry_date)
        try:
            bars = await asyncio.to_thread(self.bars_fn, doc.symbol, doc.created_at, end)
        except Exception as e:
            logging.warning(f"[{self.name}] {doc.id} 取日 K 失败，回落到模型自己查价：{e}")
            return None
        if not bars:
            return None
        return window_facts(doc, bars, today)

    async def process(self, items: list) -> list:
        today = self.today_fn()
        cohort = sorted(self._cohort(today), key=lambda d: (d.expiry_date, d.id))
        todo = cohort[:self.max_per_run]
        skipped = len(cohort) - len(todo)
        logging.info(f"[{self.name}] {today} 档期 {len(cohort)} 份，本次处理 {len(todo)} 份")

        messages: List[InvestmentMessage] = []
        reviewed: List[AdviceDoc] = []
        failed = 0
        for doc in todo:
            try:
                current = self.store.load(doc.id)
                facts = await self._price_facts(current, today)
                raw = await self.llm.complete(build_review_prompt(current, self.kind, today, facts))
                if facts is not None:
                    # 价格行整行由程序写，模型写的数字不落盘
                    raw = replace_review_line(raw, "- 价格：", price_line(current, facts))
                updated = self.store.append_review(doc.id, raw, self.kind, on=today)
            except Exception as e:
                failed += 1
                logging.error(f"[{self.name}] 复盘 {doc.id} 失败: {e}", exc_info=True)
                continue
            if updated is not None:
                reviewed.append(updated)
                messages.append(InvestmentMessage(format_review_message(updated, self.label)))

        notes = []
        if reviewed:
            self.committer.commit(commit_message(f"advice: {today.isoformat()} {self.label}", reviewed))
            if self.committer.last_error:
                notes.append(self.committer.last_error)
        if failed:
            notes.append(f"失败 {failed} 条")
        if skipped:
            notes.append(f"跳过 {skipped} 份")
        if notes:
            text = "；".join(notes)
            if messages:
                messages[-1].markdown += "\n\n" + text
            else:
                messages.append(InvestmentMessage(f"**{self.label} {today}** {text}"))
        return messages

    def _cohort(self, today: date) -> List[AdviceDoc]:
        if self.kind == "due":
            return self.store.list_due(today)
        start, end = previous_week(today) if self.kind == "weekly" else previous_month(today)
        return self.store.list_created_between(start, end)


_URL = re.compile(r"\s*[（(]?\s*https?://[^\s）)]+\s*[）)]?")


def _strip_urls(text: str) -> str:
    return _URL.sub("", text).strip()


def format_review_message(doc: AdviceDoc, label: str) -> str:
    """推送只发结论和要点（价格、逻辑、经验）；事件过程和来源链接留在文件里。

    没有「结论」行的旧复盘按原样整段推送。
    """
    review = doc.reviews[-1]
    head = f"**{label}｜{doc.id}｜{doc.symbol} {doc.name}｜{doc.direction}**"
    conclusion = review_line(review, "- 结论：")
    if not conclusion:
        body = review.split("\n", 1)[1] if "\n" in review else ""
        return f"{head}\n{body.strip()}"
    lines = [head, f"**{_strip_urls(conclusion)}**", ""]
    for marker in ("价格", "逻辑", "经验"):
        text = _strip_urls(review_line(review, f"- {marker}："))
        if text and not (marker == "经验" and is_blank_lesson(text)):
            lines.append(f"{marker}：{text}")
    return "\n".join(lines).strip()
