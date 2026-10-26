"""投资建议文档：文首字段 + 五节正文 + 追加的复盘。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from config.investment import MAX_HORIZON_DAYS, MAX_REFERENCE_AGE_DAYS

DIRECTIONS = ("看多", "看空", "观望")
STATUSES = ("open", "closed")
SECTIONS = ("理由", "目标价", "失效条件", "参考价", "观察条件")
REVIEW_TITLE_PREFIX = "复盘"
REVIEW_KINDS = {"due": "到期结案", "weekly": "周回溯", "monthly": "月回溯"}
REVIEW_LINES = ("- 价格：", "- 逻辑：", "- 事件过程：", "- 经验：")
NO_NEW_FINDING = "NO_NEW_FINDING"

_A_SHARE_SUFFIX = re.compile(r"(?<=^\d{6})\.(SS|SH|SZ|BJ)$")
_A_SHARE_PREFIX = re.compile(r"^(SH|SZ|BJ)(?=\d{6}$)")

_DATE_FIELDS = ("created_at", "expiry_date", "reference_date")
_PRICE_FIELDS = ("reference_price", "target_price", "stop_price")
_FIELD_ORDER = (
    "id", "created_at", "expiry_date", "status", "symbol", "name", "direction",
    "currency", "reference_price", "reference_date", "reference_url",
    "target_price", "stop_price",
)
_REQUIRED = (
    "created_at", "expiry_date", "symbol", "name", "direction", "currency",
    "reference_price", "reference_date", "reference_url", "target_price",
)


@dataclass
class AdviceDoc:
    id: str = ""
    created_at: Optional[date] = None
    expiry_date: Optional[date] = None
    status: str = "open"
    symbol: str = ""
    name: str = ""
    direction: str = ""
    currency: str = ""
    reference_price: Optional[float] = None
    reference_date: Optional[date] = None
    reference_url: str = ""
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    sections: Dict[str, str] = field(default_factory=dict)
    reviews: List[str] = field(default_factory=list)


@dataclass
class InvestmentMessage:
    markdown: str


def parse_fields(lines: Iterable[str]) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip()
    return fields


def split_body(body: str) -> Tuple[Dict[str, str], List[str]]:
    """按 ``## `` 切正文。``## 复盘 ...`` 进 reviews 并保留标题，其余进 sections。"""
    sections: Dict[str, str] = {}
    reviews: List[str] = []
    title: Optional[str] = None
    buf: List[str] = []

    def flush():
        if title is None:
            return
        content = "\n".join(buf).strip()
        if title.startswith(REVIEW_TITLE_PREFIX):
            reviews.append(f"## {title}\n{content}".rstrip())
        else:
            sections[title] = content

    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            title = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return sections, reviews


def doc_from_parts(fields: Dict[str, str], body: str) -> AdviceDoc:
    doc = AdviceDoc()
    for key, raw in fields.items():
        if key in _DATE_FIELDS:
            setattr(doc, key, _to_date(raw))
        elif key in _PRICE_FIELDS:
            setattr(doc, key, _to_float(raw))
        elif key in _FIELD_ORDER:
            setattr(doc, key, raw)
    doc.sections, doc.reviews = split_body(body)
    return doc


def parse_advice_markdown(text: str) -> AdviceDoc:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("建议文档缺少文首")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("建议文档文首未闭合") from None
    return doc_from_parts(parse_fields(lines[1:end]), "\n".join(lines[end + 1:]))


def render_advice_markdown(doc: AdviceDoc) -> str:
    head = ["---"]
    for key in _FIELD_ORDER:
        value = getattr(doc, key)
        if value is None:
            continue
        head.append(f"{key}: {_format_value(value)}")
    head.append("---")

    blocks = []
    ordered = list(SECTIONS) + [k for k in doc.sections if k not in SECTIONS]
    for title in ordered:
        if title in doc.sections:
            blocks.append(f"## {title}\n{doc.sections[title].strip()}")
    blocks.extend(review.strip() for review in doc.reviews)
    return "\n".join(head) + "\n\n" + "\n\n".join(blocks) + "\n"


def validate_advice(doc: AdviceDoc, open_symbols: Iterable[str] = frozenset()) -> List[str]:
    errors: List[str] = []
    for key in _REQUIRED:
        if getattr(doc, key) in (None, ""):
            errors.append(f"缺少字段 {key}")
    for title in SECTIONS:
        if not doc.sections.get(title, "").strip():
            errors.append(f"章节「{title}」为空")
    if doc.direction and doc.direction not in DIRECTIONS:
        errors.append(f"方向非法：{doc.direction}")
    if doc.status not in STATUSES:
        errors.append(f"状态非法：{doc.status}")

    for key, label in (("reference_price", "参考价"), ("target_price", "目标价"), ("stop_price", "失效价")):
        value = getattr(doc, key)
        if value is not None and value <= 0:
            errors.append(f"{label}必须为正数")
    if doc.reference_url and not doc.reference_url.startswith(("http://", "https://")):
        errors.append("参考价链接必须以 http:// 或 https:// 开头")

    if doc.created_at and doc.reference_date:
        if doc.reference_date > doc.created_at:
            errors.append("参考价日期晚于创建日")
        elif doc.created_at - doc.reference_date > timedelta(days=MAX_REFERENCE_AGE_DAYS):
            errors.append(f"参考价日期早于创建日 {MAX_REFERENCE_AGE_DAYS} 天以上")
    if doc.created_at and doc.expiry_date:
        if doc.expiry_date < doc.created_at:
            errors.append("到期日早于创建日")
        elif doc.expiry_date > doc.created_at + timedelta(days=MAX_HORIZON_DAYS):
            errors.append(f"到期日超过创建日起 {MAX_HORIZON_DAYS} 天")

    ref, target, stop = doc.reference_price, doc.target_price, doc.stop_price
    if ref is not None and target is not None:
        if doc.direction == "看多":
            if target <= ref:
                errors.append("看多目标价必须高于参考价")
            if stop is not None and stop >= ref:
                errors.append("看多失效价必须低于参考价")
        elif doc.direction == "看空":
            if target >= ref:
                errors.append("看空目标价必须低于参考价")
            if stop is not None and stop <= ref:
                errors.append("看空失效价必须高于参考价")
        elif doc.direction == "观望" and stop is not None:
            if (target - ref) * (stop - ref) >= 0:
                errors.append("观望失效价必须与目标价分居参考价两侧")

    taken = {normalize_symbol(s) for s in open_symbols}
    if doc.symbol and normalize_symbol(doc.symbol) in taken:
        errors.append(f"标的 {doc.symbol} 已有未到期建议")
    return errors


def normalize_symbol(symbol: str) -> str:
    """去重用：大写，去掉 A 股的交易所前后缀（601857.SS / SH601857 → 601857）。"""
    s = symbol.strip().upper()
    s = _A_SHARE_SUFFIX.sub("", s)
    return _A_SHARE_PREFIX.sub("", s)


def check_review_note(note: str, kind: str) -> Optional[str]:
    """校验模型给的复盘节。周/月档的 NO_NEW_FINDING 返回 None；不合格抛 ValueError。"""
    if kind not in REVIEW_KINDS:
        raise ValueError(f"未知复盘种类：{kind}")
    text = (note or "").strip()
    if text == NO_NEW_FINDING:
        if kind == "due":
            raise ValueError("到期结案不能返回 NO_NEW_FINDING")
        return None
    start = text.find(f"## {REVIEW_TITLE_PREFIX}")
    if start < 0:
        raise ValueError("复盘缺少「## 复盘」标题")
    lines = text[start:].splitlines()
    body = [("#" + line) if line.startswith("## ") else line for line in lines[1:]]
    cleaned = "\n".join([lines[0].strip()] + body).strip()
    missing = [marker for marker in REVIEW_LINES if marker not in cleaned]
    if missing:
        raise ValueError(f"复盘缺少：{'、'.join(missing)}")
    return cleaned


def review_line(review: str, marker: str) -> str:
    for line in review.splitlines():
        if line.startswith(marker):
            return line[len(marker):].strip()
    return ""


def _to_date(raw: str) -> Optional[date]:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _to_float(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def format_price(value: float) -> str:
    return str(int(value)) if value.is_integer() else repr(value)


def _format_value(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return format_price(value)
    return str(value)
