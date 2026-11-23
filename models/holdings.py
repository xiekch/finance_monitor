"""持仓配置：解析和校验。估值见 analyzers/portfolio.py。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from config.holdings import CASH_CURRENCIES, MARKET_CURRENCY

_HOLDING_KEYS = frozenset(
    {"symbol", "market", "name", "quantity", "cost", "multiplier", "thesis", "exit_when",
     "alert_day_pct", "alert_window_pct", "since"}
)
_RULE_KEYS = frozenset({"max_position_pct", "min_cash_pct", "horizon"})
_TOP_KEYS = frozenset({"cash", "rules", "holdings", "since"})

_SYMBOL_SUFFIX = re.compile(r"\.[A-Z]+$")
_SYMBOL_PREFIX = re.compile(r"^(SH|SZ|BJ|HK)(?=\d+$)")


class HoldingsConfigError(ValueError):
    """持仓配置读不到或不合法。消息直接推给使用者。"""


@dataclass
class Holding:
    symbol: str
    market: str
    name: str
    quantity: float
    cost: float
    multiplier: float = 1.0
    thesis: str = ""
    exit_when: str = ""
    # 盯盘阈值（%），不填用 config/minute_targets.py 的默认值
    alert_day_pct: Optional[float] = None     # 相对昨收
    alert_window_pct: Optional[float] = None  # 相对 30 分钟前
    # 持有起始日：除息日晚于这天的现金分红才计入盈亏。不填且顶层也没有 since 就不算分红。
    since: Optional[date] = None

    @property
    def currency(self) -> str:
        return MARKET_CURRENCY[self.market]

    @property
    def label(self) -> str:
        return f"{self.symbol} {self.name}"


@dataclass
class Rules:
    max_position_pct: Optional[float] = None
    min_cash_pct: Optional[float] = None
    horizon: str = ""


@dataclass
class HoldingsConfig:
    holdings: List[Holding] = field(default_factory=list)
    cash: Dict[str, float] = field(default_factory=dict)
    rules: Rules = field(default_factory=Rules)


def symbol_key(symbol: str) -> str:
    """比对用：大写，去掉交易所前后缀和数字代码的前导零（0700.HK / 00700 → 700）。"""
    s = symbol.strip().upper()
    s = _SYMBOL_PREFIX.sub("", _SYMBOL_SUFFIX.sub("", s))
    if s.isdigit():
        return s.lstrip("0") or "0"
    return s


def parse_holdings_config(data: Dict[str, Any]) -> HoldingsConfig:
    """把 TOML 读出的 dict 转成配置。所有问题一次报出。"""
    errors: List[str] = []
    for key in sorted(set(data) - _TOP_KEYS):
        errors.append(f"不认识的小节 {key}")

    default_since = None
    if "since" in data:
        default_since = _parse_since(data["since"])
        if default_since is None:
            errors.append(_SINCE_PROBLEM.replace("since", "顶层 since", 1))
    config = HoldingsConfig(
        holdings=_parse_holdings(data.get("holdings", []), errors, default_since),
        cash=_parse_cash(data.get("cash", {}), errors),
        rules=_parse_rules(data.get("rules", {}), errors),
    )
    if not errors and not config.holdings and not config.cash:
        errors.append("没有持仓也没有现金")
    if errors:
        raise HoldingsConfigError("持仓配置有误：" + "；".join(errors))
    return config


_SINCE_PROBLEM = "since 要写成日期，如 since = 2026-10-23（不加引号）"


def _parse_since(value: Any) -> Optional[date]:
    """TOML 的日期读出来是 date；带时间的取日期部分。字符串、数字都不认。"""
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _parse_holdings(
    raw: Any, errors: List[str], default_since: Optional[date] = None,
) -> List[Holding]:
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        errors.append("holdings 要写成 [[holdings]] 列表")
        return []
    holdings: List[Holding] = []
    seen: Dict[str, int] = {}
    for index, item in enumerate(raw, start=1):
        symbol = item.get("symbol")
        where = f"holdings 第 {index} 项" + (f"（{symbol}）" if symbol not in (None, "") else "")
        problems = _holding_problems(item)
        if not problems:
            key = symbol_key(symbol)
            if key in seen:
                problems.append(f"symbol 与第 {seen[key]} 项重复")
            else:
                seen[key] = index
        if problems:
            errors.extend(f"{where} {p}" for p in problems)
            continue
        holdings.append(Holding(
            symbol=symbol.strip(),
            market=item["market"].strip().upper(),
            name=item["name"].strip(),
            quantity=float(item["quantity"]),
            cost=float(item["cost"]),
            multiplier=float(item.get("multiplier", 1)),
            thesis=item.get("thesis", "").strip(),
            exit_when=item.get("exit_when", "").strip(),
            alert_day_pct=float(item["alert_day_pct"]) if "alert_day_pct" in item else None,
            alert_window_pct=(
                float(item["alert_window_pct"]) if "alert_window_pct" in item else None
            ),
            since=_parse_since(item["since"]) if "since" in item else default_since,
        ))
    return holdings


def _holding_problems(item: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    for key in sorted(set(item) - _HOLDING_KEYS):
        problems.append(f"不认识的字段 {key}")

    symbol = item.get("symbol")
    if symbol is None:
        problems.append("缺少 symbol")
    elif not isinstance(symbol, str):
        problems.append("symbol 要写成带引号的字符串")
    elif not symbol.strip():
        problems.append("symbol 为空")

    market = item.get("market")
    if market is None:
        problems.append("缺少 market")
    elif not isinstance(market, str) or market.strip().upper() not in MARKET_CURRENCY:
        problems.append(f"market 不认识：{market}，可选 {' / '.join(MARKET_CURRENCY)}")

    name = item.get("name")
    if name is None:
        problems.append("缺少 name")
    elif not isinstance(name, str) or not name.strip():
        problems.append("name 要写成非空字符串")

    for key in ("quantity", "cost"):
        if key not in item:
            problems.append(f"缺少 {key}")
        elif not _is_positive(item[key]):
            problems.append(f"{key} 必须是正数")
    if "multiplier" in item and not _is_positive(item["multiplier"]):
        problems.append("multiplier 必须是正数")
    for key in ("alert_day_pct", "alert_window_pct"):
        if key in item and not _is_positive(item[key]):
            problems.append(f"{key} 必须是正数")
    for key in ("thesis", "exit_when"):
        if key in item and not isinstance(item[key], str):
            problems.append(f"{key} 要写成字符串")
    if "since" in item and _parse_since(item["since"]) is None:
        problems.append(_SINCE_PROBLEM)
    return problems


def _parse_cash(raw: Any, errors: List[str]) -> Dict[str, float]:
    if not isinstance(raw, dict):
        errors.append("cash 要写成 [cash] 小节")
        return {}
    cash: Dict[str, float] = {}
    for currency, amount in raw.items():
        code = str(currency).upper()
        if code not in CASH_CURRENCIES:
            errors.append(f"cash 不支持币种 {currency}，可选 {' / '.join(CASH_CURRENCIES)}")
        elif not _is_number(amount) or amount < 0:
            errors.append(f"cash 的 {currency} 必须是不小于 0 的数字")
        elif amount > 0:
            cash[code] = float(amount)
    return cash


def _parse_rules(raw: Any, errors: List[str]) -> Rules:
    if not isinstance(raw, dict):
        errors.append("rules 要写成 [rules] 小节")
        return Rules()
    for key in sorted(set(raw) - _RULE_KEYS):
        errors.append(f"rules 里不认识的字段 {key}")
    rules = Rules()
    for key in ("max_position_pct", "min_cash_pct"):
        if key not in raw:
            continue
        value = raw[key]
        if not _is_number(value) or not 0 < value <= 100:
            errors.append(f"rules 的 {key} 必须在 0 到 100 之间")
        else:
            setattr(rules, key, float(value))
    horizon = raw.get("horizon", "")
    if not isinstance(horizon, str):
        errors.append("rules 的 horizon 要写成字符串")
    else:
        rules.horizon = horizon.strip()
    return rules


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_positive(value: Any) -> bool:
    return _is_number(value) and value > 0
