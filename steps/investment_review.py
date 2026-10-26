"""投资复盘：到期结案、周回溯、月回溯。每份文件单独调用模型，只追加不改写。"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Callable, List

from clients.llm_client.factory import build_investment_llm_client
from config.investment import ADVICE_ROOT, MAX_REVIEWS_PER_RUN
from models.advice import REVIEW_KINDS, AdviceDoc, InvestmentMessage, commit_message
from steps.base import Step
from steps.investment_parse import build_review_prompt
from storage.advice_git import AdviceCommitter
from storage.advice_store import AdviceStore, previous_month, previous_week


class ReviewStep(Step):
    def __init__(self, kind: str, store_root: Path = ADVICE_ROOT, llm=None, committer=None,
                 max_per_run: int = MAX_REVIEWS_PER_RUN,
                 today_fn: Callable[[], date] = date.today):
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
                raw = await self.llm.complete(build_review_prompt(current, self.kind, today))
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


def format_review_message(doc: AdviceDoc, label: str) -> str:
    body = doc.reviews[-1].split("\n", 1)[1] if "\n" in doc.reviews[-1] else ""
    return f"**{label}｜{doc.id}｜{doc.symbol} {doc.name}｜{doc.direction}**\n{body.strip()}"
