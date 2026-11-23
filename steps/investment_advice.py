"""投资建议：读未到期摘要和经验，让模型搜索后给出 0～3 条（没把握就不发），校验落盘并提交。"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, List, Tuple

from analyzers.advice_facts import check_reference_price
from clients.llm_client.factory import build_investment_llm_client
from config.investment import ADVICE_ROOT, LESSON_LIMIT, REFERENCE_PRICE_TOLERANCE
from fetchers import price_history
from models.advice import SECTIONS, AdviceDoc, InvestmentMessage, commit_message, format_price
from steps.base import Step
from steps.investment_parse import build_advice_prompt, parse_advice_response, parse_no_advice
from storage.advice_git import AdviceCommitter
from storage.advice_store import AdviceStore


class AdviceStep(Step):
    def __init__(self, store_root: Path = ADVICE_ROOT, llm=None, committer=None,
                 today_fn: Callable[[], date] = date.today, bars_fn=None):
        self.name = "AdviceStep"
        self.store = AdviceStore(store_root)
        self.llm = llm or build_investment_llm_client()
        self.committer = committer or AdviceCommitter()
        self.today_fn = today_fn
        # 运行时再取模块属性，测试里替换 fetch_daily_bars 才会生效
        self.bars_fn = bars_fn or price_history.fetch_daily_bars

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

        skipped_reason = parse_no_advice(raw)
        if skipped_reason is not None:
            # 模型主动放弃是正常结果：不写文件、不提交、不推送，只记日志。
            logging.info(f"[{self.name}] {today} 模型认为今天没有值得发的建议：{skipped_reason or '未写原因'}")
            return []

        valid, dropped = parse_advice_response(raw, today, self.store.open_symbols(today))
        valid, mismatched = await self._drop_wrong_reference_prices(valid)
        dropped += mismatched
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


    async def _drop_wrong_reference_prices(self, docs: List[AdviceDoc]) -> Tuple[List[AdviceDoc], int]:
        """用 reference_date 当天日 K 校验参考价，对不上的丢弃。取不到日 K 的品种放行。"""
        kept: List[AdviceDoc] = []
        dropped = 0
        for doc in docs:
            reason = None
            try:
                bars = await asyncio.to_thread(
                    self.bars_fn, doc.symbol, doc.reference_date - timedelta(days=7), doc.reference_date,
                )
                if bars:
                    reason = check_reference_price(
                        doc.reference_price, bars, doc.reference_date, REFERENCE_PRICE_TOLERANCE,
                    )
            except Exception as e:
                logging.warning(f"[{self.name}] {doc.symbol} 校验参考价时取日 K 失败，放行：{e}")
            if reason:
                dropped += 1
                logging.warning(f"[{self.name}] 丢弃 {doc.symbol}：{reason}")
                continue
            kept.append(doc)
        return kept, dropped


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
