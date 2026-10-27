"""投资建议：读未到期摘要和经验，让模型搜索后给出 1～3 条，校验落盘并提交。"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Callable, List

from clients.llm_client.factory import build_investment_llm_client
from config.investment import ADVICE_ROOT, LESSON_LIMIT
from models.advice import SECTIONS, AdviceDoc, InvestmentMessage, commit_message, format_price
from steps.base import Step
from steps.investment_parse import build_advice_prompt, parse_advice_response
from storage.advice_git import AdviceCommitter
from storage.advice_store import AdviceStore


class AdviceStep(Step):
    def __init__(self, store_root: Path = ADVICE_ROOT, llm=None, committer=None,
                 today_fn: Callable[[], date] = date.today):
        self.name = "AdviceStep"
        self.store = AdviceStore(store_root)
        self.llm = llm or build_investment_llm_client()
        self.committer = committer or AdviceCommitter()
        self.today_fn = today_fn

    async def process(self, items: list) -> list:
        today = self.today_fn()
        try:
            prompt = build_advice_prompt(
                today, self.store.open_summaries(today), self.store.recent_lessons(LESSON_LIMIT),
            )
            raw = await self.llm.complete(prompt)
        except Exception as e:
            logging.error(f"[{self.name}] 模型调用失败: {e}", exc_info=True)
            return [InvestmentMessage(f"**投资建议 {today}** 生成失败：{e}")]

        valid, dropped = parse_advice_response(raw, today, self.store.open_symbols(today))
        saved: List[AdviceDoc] = []
        for doc in valid:
            try:
                saved.append(self.store.save_new(doc))
            except Exception as e:
                dropped += 1
                logging.error(f"[{self.name}] 保存 {doc.symbol} 失败: {e}", exc_info=True)
        if not saved:
            return [InvestmentMessage(
                f"**投资建议 {today}** 生成失败：没有合法建议，丢弃 {dropped} 条，未写入文件"
            )]

        self.committer.commit(commit_message(f"advice: {today.isoformat()} 新增", saved))
        messages = [InvestmentMessage(format_advice_message(doc)) for doc in saved]
        notes = []
        if dropped:
            notes.append(f"丢弃 {dropped} 条")
        if self.committer.last_error:
            notes.append(self.committer.last_error)
        if notes:
            messages[-1].markdown += "\n\n" + "；".join(notes)
        logging.info(f"[{self.name}] 保存 {len(saved)} 条，丢弃 {dropped} 条")
        return messages


def format_advice_message(doc: AdviceDoc) -> str:
    stop = f" · 失效价 {format_price(doc.stop_price)}" if doc.stop_price is not None else ""
    head = [
        f"**投资建议 {doc.id}｜{doc.symbol} {doc.name}｜{doc.direction}**",
        f"参考价 {format_price(doc.reference_price)} {doc.currency}（{doc.reference_date.isoformat()}）"
        f" · 目标价 {format_price(doc.target_price)}{stop} · 到期 {doc.expiry_date.isoformat()}",
    ]
    if doc.summary:
        head.append(doc.summary)
    sections = [
        f"**{title}**\n{body}"
        for title in SECTIONS
        if (body := doc.sections.get(title, "").strip())
    ]
    text = "\n".join(head)
    return text + ("\n\n" + "\n\n".join(sections) if sections else "")
