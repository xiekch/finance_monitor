"""投资建议与复盘：拼提示词、解析模型输出。"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Iterable, List, Optional, Tuple

from config.investment import (
    ADVICE_PROMPT_TEMPLATE,
    MAX_ADVICE,
    MAX_HORIZON_DAYS,
    MAX_REFERENCE_AGE_DAYS,
    REVIEW_KIND_RULES,
    REVIEW_PROMPT_TEMPLATE,
)
from models.advice import (
    REVIEW_KINDS,
    AdviceDoc,
    check_review_note,
    doc_from_parts,
    parse_fields,
    render_advice_markdown,
    validate_advice,
)

_ADVICE_BLOCK = re.compile(r"<<<ADVICE>>>(.*?)<<<END>>>", re.S)


def build_advice_prompt(today: date, open_summaries: List[str], lessons: List[str]) -> str:
    return ADVICE_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        max_advice=MAX_ADVICE,
        earliest_reference=(today - timedelta(days=MAX_REFERENCE_AGE_DAYS)).isoformat(),
        latest_expiry=(today + timedelta(days=MAX_HORIZON_DAYS)).isoformat(),
        open_block="\n".join(f"- {line}" for line in open_summaries) or "（无）",
        lessons_block="\n\n".join(lessons) or "（无）",
    )


def build_review_prompt(doc: AdviceDoc, kind: str, today: date) -> str:
    return REVIEW_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        kind_label=REVIEW_KINDS[kind],
        window_start=doc.created_at.isoformat(),
        window_end=min(today, doc.expiry_date).isoformat(),
        kind_rule=REVIEW_KIND_RULES[kind],
        doc=render_advice_markdown(doc),
    )


def parse_advice_response(raw: str, today: date,
                          open_symbols: Iterable[str]) -> Tuple[List[AdviceDoc], int]:
    """返回合法建议和丢弃条数。同一标的只收第一条，最多 MAX_ADVICE 条。"""
    valid: List[AdviceDoc] = []
    dropped = 0
    taken = set(open_symbols)
    for match in _ADVICE_BLOCK.finditer(raw or ""):
        doc = _block_to_doc(match.group(1), today)
        if len(valid) >= MAX_ADVICE:
            dropped += 1
            logging.warning(f"[investment_parse] 超过 {MAX_ADVICE} 条，丢弃 {doc.symbol}")
            continue
        errors = validate_advice(doc, open_symbols=taken)
        if errors:
            dropped += 1
            logging.warning(f"[investment_parse] 丢弃 {doc.symbol or '?'}：{'；'.join(errors)}")
            continue
        valid.append(doc)
        taken.add(doc.symbol)
    return valid, dropped


def parse_review_response(raw: str, kind: str) -> Optional[str]:
    return check_review_note(raw, kind)


def _block_to_doc(block: str, today: date) -> AdviceDoc:
    lines = block.strip("\n").splitlines()
    split = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    doc = doc_from_parts(parse_fields(lines[:split]), "\n".join(lines[split:]))
    doc.id = ""
    doc.created_at = today
    doc.status = "open"
    return doc
