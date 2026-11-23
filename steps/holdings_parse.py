"""持仓分析：拼提示词、解析和校验模型回复。现价由程序取，模型只给动作和依据。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from analyzers.portfolio import Portfolio, Position
from config.holdings import (
    ACTIONS,
    HOLD,
    HOLDINGS_PROMPT_TEMPLATE,
    MARKET_LABELS,
    NEWS_WINDOW_DAYS,
    PORTFOLIO_TITLE,
)
from models.advice import format_price, split_body
from models.holdings import Holding, HoldingsConfig, Rules, symbol_key

_FIELD_LINE = re.compile(r"^\s*[-*]\s*[*`]*([A-Za-z_]+)[*`]*\s*[:：]\s*(.*)$")
_SYMBOL_TOKEN = re.compile(r"[A-Za-z0-9.^]+")
_URL = re.compile(r"https?://[^\s<>()\[\]（）。，；、]+")
_EMPTY = "（未填写）"
_NONE = "（无）"

PreviousActions = Optional[Tuple[date, Dict[str, str]]]


@dataclass
class HoldingAdvice:
    holding: Holding
    action: str = ""
    target_weight: str = ""
    summary: str = ""
    sections: Dict[str, str] = field(default_factory=dict)
    # 建议未通过校验的原因；空串表示通过。
    problem: str = ""


@dataclass
class ParsedAdvice:
    advice: Dict[str, HoldingAdvice] = field(default_factory=dict)
    portfolio_sections: Dict[str, str] = field(default_factory=dict)
    unknown: List[str] = field(default_factory=list)

    def missing(self, holdings: Iterable[Holding]) -> List[Holding]:
        return [h for h in holdings if h.symbol not in self.advice]


# ── 提示词 ─────────────────────────────────────────────


def build_holdings_prompt(
    today: date,
    config: HoldingsConfig,
    portfolio: Portfolio,
    open_summaries: List[str],
    lessons: List[str],
    previous: PreviousActions,
) -> str:
    """portfolio 要先用现价估过值（apply_prices）。"""
    return HOLDINGS_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        news_days=NEWS_WINDOW_DAYS,
        holdings_block=_holdings_block(portfolio),
        cash_pct=_pct(portfolio.cash_pct),
        rules_block=_rules_block(config.rules),
        breach_block=_breach_block(config.rules, portfolio),
        open_block="\n".join(f"- {line}" for line in open_summaries) or _NONE,
        prev_block=_previous_block(config.holdings, previous),
        lessons_block="\n\n".join(lessons) or _NONE,
    )


def _holdings_block(portfolio: Portfolio) -> str:
    """只给价格和比例。数量和金额不进提示词。"""
    blocks = []
    for position in portfolio.positions:
        h = position.holding
        blocks.append("\n".join([
            f"### {h.label}",
            f"- 市场：{MARKET_LABELS[h.market]}，币种 {h.currency}",
            f"- 成本价：{format_price(float(h.cost))}",
            *_price_lines(position),
            f"- 持有理由：{_one_line(h.thesis) or _EMPTY}",
            f"- 卖出条件：{_one_line(h.exit_when) or _EMPTY}",
        ]))
    return "\n\n".join(blocks) or "（没有持仓，只有现金）"


def _price_lines(position: Position) -> List[str]:
    if position.price is None:
        return [
            "- 现价：程序没有取到",
            "- 盈亏：未知",
            f"- 占比：没有计入总资产（按买入成本算约 {position.cost_weight_pct:.1f}%）",
        ]
    return [
        f"- 现价：{format_price(position.price)}（{position.price_date.isoformat()}）",
        f"- 盈亏：{position.pnl_pct:+.1f}%" + ("（含已收分红）" if position.dividend_cny else ""),
        f"- 占比：{position.weight_pct:.1f}%",
    ]


def _rules_block(rules: Rules) -> str:
    lines = []
    if rules.max_position_pct is not None:
        lines.append(f"- 单个持仓的市值占比不超过 {rules.max_position_pct:g}%")
    if rules.min_cash_pct is not None:
        lines.append(f"- 现金占比不低于 {rules.min_cash_pct:g}%")
    if rules.horizon:
        lines.append(f"- 投资期限：{_one_line(rules.horizon)}")
    return "\n".join(lines) or "（没有设定规则）"


def _breach_block(rules: Rules, portfolio: Portfolio) -> str:
    lines = [f"- {breach}" for breach in portfolio.breaches]
    if portfolio.positions and portfolio.unpriced:
        lines.append("- 有持仓没取到现价，没有计入总资产，其余持仓和现金的占比因此偏高")
    if lines:
        return "\n".join(lines)
    has_limits = rules.max_position_pct is not None or rules.min_cash_pct is not None
    return "（没有超出规则）" if has_limits else "（没有设定占比规则）"


def _pct(value: Optional[float]) -> str:
    return "未知" if value is None else f"{value:.1f}%"


def _previous_block(holdings: List[Holding], previous: PreviousActions) -> str:
    """只放上次的动作，并标明可能是错的：整段旧结论放进来会被模型照搬。"""
    if previous is not None:
        day, actions = previous
        lines = [f"- {h.label}：{actions[h.symbol]}" for h in holdings if h.symbol in actions]
        if lines:
            return (
                f"下面是 {day.isoformat()} 模型给出的动作，可能是错的。"
                "动作和上次不同时，在「依据」里写明是哪条新事实改变了结论；"
                "动作相同又没有新信息时，「依据」写「无新变化」，不要重复上次的论述。\n"
                + "\n".join(lines)
            )
    return "这是第一次分析，没有上一次的结论。"


def _one_line(text: str) -> str:
    return " ".join(text.split())


# ── 解析 ───────────────────────────────────────────────


def parse_holdings_response(raw: Optional[str], holdings: List[Holding]) -> ParsedAdvice:
    """每个持仓只收第一块；对不上持仓的标题记到 unknown。"""
    by_key = {symbol_key(h.symbol): h for h in holdings}
    result = ParsedAdvice()
    for title, lines in _split_blocks(raw or ""):
        if title.startswith(PORTFOLIO_TITLE):
            result.portfolio_sections, _ = split_body("\n".join(lines))
            continue
        token = _SYMBOL_TOKEN.match(title)
        holding = by_key.get(symbol_key(token.group(0))) if token else None
        if holding is None:
            result.unknown.append(title)
            continue
        if holding.symbol in result.advice:
            continue
        result.advice[holding.symbol] = _block_to_advice(holding, lines)
    return result


def _split_blocks(raw: str) -> List[Tuple[str, List[str]]]:
    """按一级标题切块，标题之前的说明文字和 ``` 围栏行都丢掉。"""
    blocks: List[Tuple[str, List[str]]] = []
    for line in raw.splitlines():
        if line.strip().startswith("```"):
            continue
        if line.startswith("# "):
            blocks.append((line[2:].strip(), []))
        elif blocks:
            blocks[-1][1].append(line)
    return blocks


def _block_to_advice(holding: Holding, lines: List[str]) -> HoldingAdvice:
    split = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    fields: Dict[str, str] = {}
    for line in lines[:split]:
        match = _FIELD_LINE.match(line)
        if match:
            fields[match.group(1).lower()] = match.group(2).strip().strip("`").strip()
    sections, _ = split_body("\n".join(lines[split:]))
    return HoldingAdvice(
        holding=holding,
        action=fields.get("action", ""),
        target_weight=fields.get("target_weight", ""),
        summary=fields.get("summary", ""),
        sections=sections,
    )


def check_action(advice: HoldingAdvice, breached: bool) -> str:
    """加仓、减仓、清仓必须有带链接的事实，或该持仓违反了规则。"""
    if advice.action not in ACTIONS:
        return f"action 非法：{advice.action or '空'}"
    basis = advice.sections.get("依据", "").strip()
    if not basis:
        return "缺少依据"
    if advice.action != HOLD and not breached and not _URL.search(basis):
        return f"{advice.action}需要带链接的事实依据"
    return ""

