"""持仓估值：成本占比、市值、盈亏、市值占比、规则检查。所有金额折成人民币。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from config.holdings import BASE_CURRENCY, NO_DIVIDEND_MARKETS
from models.holdings import Holding, HoldingsConfig, Rules

# 0.4 * 100 在浮点里是 40.00000000000001，恰好踩线不算违规。
_EPSILON = 1e-9


@dataclass
class PriceQuote:
    price: float
    day: date
    source: str = ""


@dataclass
class Dividend:
    """一次现金分红：除息日和每股（份、枚）的税前金额，币种同持仓。"""
    ex_date: date
    per_unit: float


# Position.dividend_issue：分红没能计入的原因
NO_SINCE = "no_since"          # 没设持有起始日，不知道哪些分红算在持有期内
FETCH_FAILED = "fetch_failed"  # 分红接口没取到


@dataclass
class Position:
    holding: Holding
    cost_cny: float
    cost_weight_pct: float
    price: Optional[float] = None
    price_date: Optional[date] = None
    price_source: str = ""
    value_cny: Optional[float] = None
    # 持有期内已除息的税前现金分红；None 表示没有算（见 dividend_issue）。
    dividend_cny: Optional[float] = None
    dividend_issue: str = ""
    # 盈亏 = 市值 − 成本 + 分红
    pnl_cny: Optional[float] = None
    pnl_pct: Optional[float] = None
    weight_pct: Optional[float] = None


@dataclass
class Portfolio:
    positions: List[Position]
    cash: Dict[str, float]
    cash_cny: float
    fx: Dict[str, float]
    cost_total_cny: float
    cash_cost_weight_pct: float
    # 以下在 apply_prices 之后才有值。没有现价的持仓不计入。
    total_cny: Optional[float] = None
    cash_pct: Optional[float] = None
    pnl_cny: Optional[float] = None
    pnl_pct: Optional[float] = None
    dividend_cny: Optional[float] = None   # 没传分红数据时为 None
    currency_pct: Dict[str, float] = field(default_factory=dict)
    breaches: List[str] = field(default_factory=list)
    breached_symbols: Set[str] = field(default_factory=set)
    cash_below_min: bool = False

    @property
    def unpriced(self) -> List[Position]:
        return [p for p in self.positions if p.value_cny is None]


def required_currencies(config: HoldingsConfig) -> Set[str]:
    return {h.currency for h in config.holdings} | set(config.cash)


def build_portfolio(config: HoldingsConfig, fx: Dict[str, float]) -> Portfolio:
    """按买入成本算仓位。fx 是各币种兑人民币的汇率，缺了直接报错。"""
    rates = {BASE_CURRENCY: 1.0, **fx}
    missing = sorted(required_currencies(config) - set(rates))
    if missing:
        raise ValueError(f"缺少 {'、'.join(missing)} 兑人民币的汇率")

    cash_cny = sum(amount * rates[currency] for currency, amount in config.cash.items())
    costs = [h.quantity * h.multiplier * h.cost * rates[h.currency] for h in config.holdings]
    total = cash_cny + sum(costs)
    positions = [
        Position(holding=h, cost_cny=cost, cost_weight_pct=_pct(cost, total))
        for h, cost in zip(config.holdings, costs)
    ]
    return Portfolio(
        positions=positions,
        cash=dict(config.cash),
        cash_cny=cash_cny,
        fx={c: rates[c] for c in sorted(required_currencies(config))},
        cost_total_cny=total,
        cash_cost_weight_pct=_pct(cash_cny, total),
    )


def apply_prices(
    portfolio: Portfolio, quotes: Dict[str, PriceQuote], rules: Optional[Rules] = None,
    dividends: Optional[Dict[str, List[Dividend]]] = None, today: Optional[date] = None,
) -> Portfolio:
    """用现价估值。quotes 以持仓的 symbol 为键；没有现价的持仓保持空值。

    dividends 以 symbol 为键：不传就不算分红，盈亏只有价差；传了，持有起始日（since）
    之后、today 当天及以前除息的分红记入盈亏。键不在里面表示没取到。
    """
    today = today or date.today()
    rates = {BASE_CURRENCY: 1.0, **portfolio.fx}
    by_currency: Dict[str, float] = {}
    for currency, amount in portfolio.cash.items():
        by_currency[currency] = by_currency.get(currency, 0.0) + amount * rates[currency]

    priced: List[Position] = []
    for position in portfolio.positions:
        quote = quotes.get(position.holding.symbol)
        if quote is None:
            continue
        h = position.holding
        position.price = quote.price
        position.price_date = quote.day
        position.price_source = quote.source
        position.value_cny = h.quantity * h.multiplier * quote.price * rates[h.currency]
        position.dividend_cny, position.dividend_issue = _dividend_income(
            h, dividends, today, rates[h.currency])
        position.pnl_cny = position.value_cny - position.cost_cny + (position.dividend_cny or 0.0)
        position.pnl_pct = _pct(position.pnl_cny, position.cost_cny)
        by_currency[h.currency] = by_currency.get(h.currency, 0.0) + position.value_cny
        priced.append(position)

    total = portfolio.cash_cny + sum(p.value_cny for p in priced)
    portfolio.total_cny = total
    portfolio.cash_pct = _pct(portfolio.cash_cny, total)
    for position in priced:
        position.weight_pct = _pct(position.value_cny, total)
    portfolio.currency_pct = {
        currency: _pct(value, total) for currency, value in by_currency.items() if value > 0
    }
    if priced:
        priced_cost = sum(p.cost_cny for p in priced)
        portfolio.pnl_cny = sum(p.pnl_cny for p in priced)
        portfolio.pnl_pct = _pct(portfolio.pnl_cny, priced_cost)
    if dividends is not None:
        portfolio.dividend_cny = sum(p.dividend_cny or 0.0 for p in priced)
    _check_rules(portfolio, priced, rules or Rules())
    return portfolio


def _dividend_income(
    holding: Holding, dividends: Optional[Dict[str, List[Dividend]]], today: date, rate: float,
) -> Tuple[Optional[float], str]:
    """持有期内的分红折人民币，数量按现在的数量算。返回（金额, 没算的原因）。"""
    if dividends is None:
        return None, ""
    if holding.market in NO_DIVIDEND_MARKETS:
        return 0.0, ""
    if holding.since is None:
        return None, NO_SINCE
    records = dividends.get(holding.symbol)
    if records is None:
        return None, FETCH_FAILED
    per_unit = sum(d.per_unit for d in records if holding.since < d.ex_date <= today)
    return per_unit * holding.quantity * holding.multiplier * rate, ""


def _check_rules(portfolio: Portfolio, priced: List[Position], rules: Rules) -> None:
    portfolio.breaches = []
    portfolio.breached_symbols = set()
    portfolio.cash_below_min = False
    if rules.max_position_pct is not None:
        for position in priced:
            if position.weight_pct > rules.max_position_pct + _EPSILON:
                portfolio.breached_symbols.add(position.holding.symbol)
                portfolio.breaches.append(
                    f"{position.holding.name} 占比 {position.weight_pct:.1f}%，"
                    f"超过单个持仓上限 {rules.max_position_pct:g}%"
                )
    if rules.min_cash_pct is not None and portfolio.cash_pct < rules.min_cash_pct - _EPSILON:
        portfolio.cash_below_min = True
        portfolio.breaches.append(
            f"现金占比 {portfolio.cash_pct:.1f}%，低于下限 {rules.min_cash_pct:g}%"
        )


def _pct(part: float, whole: float) -> float:
    return part / whole * 100 if whole else 0.0
