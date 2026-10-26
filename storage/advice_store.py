"""投资建议的 Markdown 存储：月份目录、原子写、按文件加锁、档期、经验摘录。"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config.investment import ADVICE_ROOT
from models.advice import (
    REVIEW_KINDS,
    AdviceDoc,
    check_review_note,
    format_price,
    parse_advice_markdown,
    render_advice_markdown,
    review_line,
)

LESSONS_FILE = "lessons.md"
_SUMMARY_CLIP = 60

# 每个 ReviewStep 各自新建 AdviceStore，锁必须挂在模块上才能互斥。
_LOCKS: Dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def previous_week(today: date) -> Tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def previous_month(today: date) -> Tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


class AdviceStore:
    def __init__(self, root: Path = ADVICE_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ── 写 ─────────────────────────────────────────────

    def save_new(self, doc: AdviceDoc) -> AdviceDoc:
        day = doc.created_at.isoformat()
        month_dir = self.root / day[:7]
        month_dir.mkdir(parents=True, exist_ok=True)
        with _lock_for(month_dir):
            pattern = re.compile(rf"^{re.escape(day)}-(\d+)\.md$")
            taken = [int(m.group(1)) for p in month_dir.iterdir() if (m := pattern.match(p.name))]
            doc.id = f"{day}-{max(taken, default=0) + 1}"
            _atomic_write(month_dir / f"{doc.id}.md", render_advice_markdown(doc))
        return doc

    def append_review(self, advice_id: str, note: str, kind: str,
                      on: Optional[date] = None) -> Optional[AdviceDoc]:
        cleaned = check_review_note(note, kind)
        if cleaned is None:
            return None
        path = self._path(advice_id)
        with _lock_for(path):
            doc = self.load(advice_id)
            if kind == "due":
                doc.status = "closed"
            doc.reviews.append(cleaned)
            _atomic_write(path, render_advice_markdown(doc))
        lesson = review_line(cleaned, "- 经验：")
        if lesson and lesson != "无":
            self.append_lesson(lesson, advice_id=doc.id, symbol=doc.symbol,
                               kind=REVIEW_KINDS[kind], on=on or date.today())
        return doc

    def append_lesson(self, text: str, *, advice_id: str, symbol: str, kind: str, on: date) -> None:
        path = self.root / LESSONS_FILE
        block = f"## {on.isoformat()} · {symbol} · {advice_id} · {kind}\n{text.strip()}\n"
        with _lock_for(path):
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if existing and not existing.endswith("\n\n"):
                existing = existing.rstrip("\n") + "\n\n"
            _atomic_write(path, existing + block)

    # ── 读 ─────────────────────────────────────────────

    def load(self, advice_id: str) -> AdviceDoc:
        doc = parse_advice_markdown(self._path(advice_id).read_text(encoding="utf-8"))
        doc.id = doc.id or advice_id
        return doc

    def all_docs(self) -> List[AdviceDoc]:
        docs = []
        for path in sorted(self.root.rglob("*.md")):
            if path.name == LESSONS_FILE:
                continue
            try:
                doc = parse_advice_markdown(path.read_text(encoding="utf-8"))
            except ValueError as e:
                logging.warning(f"[AdviceStore] 跳过无法解析的文件 {path}: {e}")
                continue
            doc.id = doc.id or path.stem
            docs.append(doc)
        return docs

    def list_due(self, today: date) -> List[AdviceDoc]:
        docs = [d for d in self.all_docs()
                if d.status == "open" and d.expiry_date and d.expiry_date < today]
        return sorted(docs, key=lambda d: (d.expiry_date, d.id))

    def list_created_between(self, start: date, end: date) -> List[AdviceDoc]:
        docs = [d for d in self.all_docs() if d.created_at and start <= d.created_at <= end]
        return sorted(docs, key=lambda d: (d.created_at, d.id))

    def list_open(self, today: date) -> List[AdviceDoc]:
        docs = [d for d in self.all_docs()
                if d.status == "open" and d.expiry_date and d.expiry_date >= today]
        return sorted(docs, key=lambda d: (d.created_at, d.id))

    def open_symbols(self, today: date) -> Set[str]:
        return {d.symbol for d in self.list_open(today)}

    def open_summaries(self, today: date) -> List[str]:
        return [_summary_line(d) for d in self.list_open(today)]

    def recent_lessons(self, limit: int) -> List[str]:
        path = self.root / LESSONS_FILE
        if not path.exists():
            return []
        blocks: List[List[str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                blocks.append([line])
            elif blocks:
                blocks[-1].append(line)
        return ["\n".join(b).strip() for b in blocks][-limit:] if limit > 0 else []

    def _path(self, advice_id: str) -> Path:
        return self.root / advice_id[:7] / f"{advice_id}.md"


def _summary_line(doc: AdviceDoc) -> str:
    reason = doc.sections.get("理由", "").strip()
    first = re.split(r"(?<=[。！？])", reason, maxsplit=1)[0].strip() if reason else ""
    if doc.reviews:
        last = doc.reviews[-1]
        parts = [_clip(review_line(last, m)) for m in ("- 价格：", "- 逻辑：")]
        latest = "；".join(p for p in parts if p) or "尚无复盘"
    else:
        latest = "尚无复盘"
    target = format_price(doc.target_price) if doc.target_price is not None else "?"
    return " | ".join([
        doc.id,
        f"{doc.symbol} {doc.name}".strip(),
        doc.direction,
        f"到期 {doc.expiry_date.isoformat()}",
        f"目标价 {target} {doc.currency}".strip(),
        first,
        latest,
    ])


def _clip(text: str) -> str:
    return text if len(text) <= _SUMMARY_CLIP else text[:_SUMMARY_CLIP] + "…"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
