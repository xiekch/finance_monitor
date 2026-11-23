"""持仓分析：读持仓配置，程序取现价并估值，模型联网查消息后给出操作建议，校验后存本地报告并推送。

持仓数量和金额只出现在本地报告里：不进提示词，不进推送，不进 git。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

from analyzers.portfolio import (
    FETCH_FAILED,
    NO_SINCE,
    Dividend,
    Portfolio,
    Position,
    PriceQuote,
    apply_prices,
    build_portfolio,
    required_currencies,
)
from clients.llm_client.factory import build_investment_llm_client
from config.holdings import (
    ADVICE_SECTIONS,
    BASE_CURRENCY,
    CURRENCY_LABELS,
    HOLD,
    HOLDINGS_FILE,
    HOLDINGS_LESSON_LIMIT,
    HOLDINGS_REPORT_ROOT,
)
from config.investment import ADVICE_ROOT, REPO_ROOT
from fetchers.holding_dividends import fetch_holding_dividends
from fetchers.holding_quotes import fetch_holding_quotes
from fetchers.sina_quote import fetch_fx_rates
from models.advice import InvestmentMessage, format_price
from models.holdings import Holding, HoldingsConfig, HoldingsConfigError, symbol_key
from steps.base import Step
from steps.holdings_parse import (
    HoldingAdvice,
    ParsedAdvice,
    build_holdings_prompt,
    check_action,
    parse_holdings_response,
)
from storage.advice_store import AdviceStore
from storage.holdings_store import HoldingsReportStore, load_holdings_config

FxFetcher = Callable[[Iterable[str]], Awaitable[Dict[str, float]]]
QuoteFetcher = Callable[[List[Holding], date], Awaitable[Dict[str, PriceQuote]]]
DividendFetcher = Callable[[List[Holding], date], Awaitable[Dict[str, List[Dividend]]]]
# 仓位违反规则只能支持往下调仓位，不能当作加仓的理由。
_REDUCING = ("减仓", "清仓")
_NOT_COVERED = "未覆盖"
_REJECTED = "未通过校验"


class HoldingsAdviceStep(Step):
    def __init__(
        self,
        config_path: Path = HOLDINGS_FILE,
        report_root: Path = HOLDINGS_REPORT_ROOT,
        advice_root: Path = ADVICE_ROOT,
        llm=None,
        fx_fetcher: FxFetcher = fetch_fx_rates,
        quote_fetcher: QuoteFetcher = fetch_holding_quotes,
        dividend_fetcher: DividendFetcher = fetch_holding_dividends,
        today_fn: Callable[[], date] = date.today,
    ):
        self.name = "HoldingsAdviceStep"
        self.config_path = Path(config_path)
        self.reports = HoldingsReportStore(report_root)
        self.advice_store = AdviceStore(advice_root)
        self.llm = llm or build_investment_llm_client()
        self.fx_fetcher = fx_fetcher
        self.quote_fetcher = quote_fetcher
        self.dividend_fetcher = dividend_fetcher
        self.today_fn = today_fn

    async def process(self, items: list) -> list:
        today = self.today_fn()
        try:
            # 每次运行都重读配置：改了持仓下一次运行就生效。
            config = load_holdings_config(self.config_path)
        except HoldingsConfigError as e:
            return self._failed(today, str(e))

        try:
            fx = await self.fx_fetcher(sorted(required_currencies(config)))
            portfolio = build_portfolio(config, fx)
        except Exception as e:
            logging.error(f"[{self.name}] 取汇率失败: {e}", exc_info=True)
            return self._failed(today, f"取不到汇率：{e}")

        try:
            quotes = await self.quote_fetcher(config.holdings, today)
        except Exception as e:
            logging.error(f"[{self.name}] 取现价失败: {e}", exc_info=True)
            return self._failed(today, f"取不到现价：{e}")
        if config.holdings and not quotes:
            return self._failed(today, "所有持仓的现价都没取到，没有调用模型")
        try:
            dividends = await self.dividend_fetcher(config.holdings, today)
        except Exception as e:
            # 分红只影响盈亏数字，取不到不拦住整份日报：报告里会标出哪些持仓没算。
            logging.error(f"[{self.name}] 取分红失败: {e}", exc_info=True)
            dividends = {}
        apply_prices(portfolio, quotes, config.rules, dividends=dividends, today=today)

        # 只和今天之前的结论比：同一天重跑不拿自己上一轮的结果当「上次」。
        previous = self.reports.latest_actions(today - timedelta(days=1))
        try:
            prompt = build_holdings_prompt(
                today=today,
                config=config,
                portfolio=portfolio,
                open_summaries=self.advice_store.open_summaries_for(
                    today, lambda symbol: _held(config.holdings, symbol)),
                lessons=self.advice_store.recent_lessons(HOLDINGS_LESSON_LIMIT),
                previous=previous,
            )
            raw = await self.llm.complete(prompt)
        except Exception as e:
            logging.error(f"[{self.name}] 模型调用失败: {e}", exc_info=True)
            return self._failed(today, f"模型调用失败：{e}")

        parsed = parse_holdings_response(raw, config.holdings)
        _check_actions(parsed, portfolio)
        valid = {s: a for s, a in parsed.advice.items() if not a.problem}

        if config.holdings and not valid:
            return self._no_valid_advice(today, raw, parsed)

        view = _View(today, config, portfolio, parsed, previous[1] if previous else {})
        note = ""
        try:
            path = self.reports.save(
                today, view.report(raw or ""), {s: a.action for s, a in valid.items()})
            note = f"含数量和金额的完整报告在本机 {_display_path(path)}"
        except OSError as e:
            logging.error(f"[{self.name}] 保存报告失败: {e}", exc_info=True)
            note = f"本地报告保存失败：{e}"
        logging.info(
            f"[{self.name}] 持仓 {len(config.holdings)} 个，合法建议 {len(valid)} 条，"
            f"现价不可用 {len(portfolio.unpriced)} 个"
        )
        return [InvestmentMessage(text) for text in view.messages(note)]

    def _no_valid_advice(self, today: date, raw: Optional[str], parsed: ParsedAdvice) -> list:
        reasons = "；".join(f"{a.holding.name}：{a.problem}" for a in parsed.advice.values())
        detail = f"（{reasons}）" if reasons else ""
        try:
            path = self.reports.save_raw(today, raw or "")
            saved = f"模型回复原文已存到本机 {_display_path(path)}"
        except OSError as e:
            logging.error(f"[{self.name}] 保存原文失败: {e}", exc_info=True)
            saved = f"模型回复原文保存失败：{e}"
        return self._failed(today, f"没有合法的持仓建议{detail}，{saved}")

    def _failed(self, today: date, reason: str) -> list:
        logging.error(f"[{self.name}] 未生成：{reason}")
        return [InvestmentMessage(f"**持仓日报 {today}** 未生成：{reason}")]


def _held(holdings: List[Holding], advice_symbol: str) -> bool:
    """advice/ 里的标的是不是当前持仓。港股在 advice/ 里带 .HK 后缀，避免 00700 撞上 A 股 000700。"""
    symbol = advice_symbol.strip().upper()
    is_hk = symbol.endswith(".HK")
    key = symbol_key(symbol)
    return any(
        symbol_key(h.symbol) == key and (h.market == "HK") == is_hk for h in holdings
    )


def _check_actions(parsed: ParsedAdvice, portfolio: Portfolio) -> None:
    for symbol, advice in parsed.advice.items():
        # 单票超上限只支持减这一只；现金低于下限时减哪只都算有规则依据。
        rule_backed = advice.action in _REDUCING and (
            portfolio.cash_below_min or symbol in portfolio.breached_symbols)
        advice.problem = check_action(advice, rule_backed)


class _View:
    """同一份结果的两种写法：推送只有比例，本地报告带数量和金额。"""

    def __init__(self, today: date, config: HoldingsConfig, portfolio: Portfolio,
                 parsed: ParsedAdvice, previous: Dict[str, str]):
        self.today = today
        self.config = config
        self.portfolio = portfolio
        self.parsed = parsed
        self.previous = previous

    # ── 推送 ───────────────────────────────────────────

    def messages(self, note: str) -> List[str]:
        texts = [self._overview(note)]
        for position in self.portfolio.positions:
            advice = self._valid_advice(position.holding)
            if advice is not None and (advice.action != HOLD or self._changed(advice)):
                texts.append(self._detail(position, advice))
        if self.parsed.portfolio_sections:
            texts.append(_sections_text("**组合**", self.parsed.portfolio_sections))
        return texts

    def _overview(self, note: str) -> str:
        p = self.portfolio
        with_dividend = "（含分红）" if p.dividend_cny else ""
        head = [
            f"**持仓日报 {self.today}**",
            f"浮动盈亏 {_signed_pct(p.pnl_pct)}{with_dividend} · 现金 {_pct(p.cash_pct)}",
        ]
        if p.currency_pct:
            ranked = sorted(p.currency_pct.items(), key=lambda kv: -kv[1])
            head.append("币种：" + " · ".join(
                f"{CURRENCY_LABELS.get(c, c)} {_pct(v)}" for c, v in ranked))

        lines = []
        for position in p.positions:
            advice = self.parsed.advice.get(position.holding.symbol)
            line = f"**{self._status(advice)}** {position.holding.label}｜{_weights(position)}"
            if advice is not None and not advice.problem and self._changed(advice):
                line += f"（上次：{self.previous[position.holding.symbol]}）"
            lines.append(line)
            if advice is not None and not advice.problem and advice.summary:
                lines.append(f"> {advice.summary}")

        blocks = ["\n".join(head)]
        if lines:
            blocks.append("\n".join(lines))
        notes = self._notes() + ([note] if note else [])
        if notes:
            blocks.append("\n".join(notes))
        return "\n\n".join(blocks)

    def _notes(self) -> List[str]:
        p = self.portfolio
        advice = self.parsed.advice
        notes = []
        if p.breaches:
            notes.append("超出规则：" + "；".join(p.breaches))
        rejected = [f"{a.holding.name}（{a.problem}）" for a in advice.values() if a.problem]
        if rejected:
            notes.append("建议未通过校验：" + "；".join(rejected))
        if p.unpriced:
            notes.append(
                "没取到现价，未计入占比和盈亏：" + "、".join(x.holding.name for x in p.unpriced)
                + "。其余持仓和现金的占比因此偏高"
            )
        failed = _with_issue(p, FETCH_FAILED)
        if failed:
            notes.append("没取到分红记录，盈亏未含分红：" + "、".join(failed))
        missing = self.parsed.missing(self.config.holdings)
        if missing:
            notes.append("模型没有覆盖：" + "、".join(h.name for h in missing))
        if self.parsed.unknown:
            notes.append("模型写了不在持仓里的标的，已忽略：" + "、".join(self.parsed.unknown))
        return notes

    def _detail(self, position: Position, advice: HoldingAdvice) -> str:
        h = position.holding
        head = [f"**{h.label}｜{advice.action}**"]
        if position.price is not None:
            head.append(
                f"现价 {format_price(position.price)} {h.currency}"
                f"（{position.price_date.isoformat()}）"
                f" · 盈亏 {_signed_pct(position.pnl_pct)}"
            )
            weight = f"占比 {_pct(position.weight_pct)}"
        else:
            head.append("现价不可用")
            weight = ""
        target = advice.target_weight.strip().rstrip("%％").strip()
        if target and advice.action != HOLD:
            weight = f"{weight} → 目标 {target}%" if weight else f"目标占比 {target}%"
        if weight:
            head.append(weight)
        if advice.summary:
            head.append(advice.summary)
        ordered = {t: advice.sections[t] for t in ADVICE_SECTIONS if t in advice.sections}
        return _sections_text("\n".join(head), ordered)

    def _status(self, advice: Optional[HoldingAdvice]) -> str:
        if advice is None:
            return _NOT_COVERED
        return _REJECTED if advice.problem else advice.action

    def _valid_advice(self, holding: Holding) -> Optional[HoldingAdvice]:
        advice = self.parsed.advice.get(holding.symbol)
        return advice if advice is not None and not advice.problem else None

    def _changed(self, advice: HoldingAdvice) -> bool:
        before = self.previous.get(advice.holding.symbol)
        return before is not None and before != advice.action

    # ── 本地报告 ───────────────────────────────────────

    def report(self, raw: str) -> str:
        p = self.portfolio
        pnl = f"{_money(p.pnl_cny, signed=True)}（{_signed_pct(p.pnl_pct)}）" if p.pnl_cny is not None else "—"
        rates = " · ".join(f"{c} {rate:g}" for c, rate in p.fx.items() if c != BASE_CURRENCY)
        lines = [
            f"# 持仓日报 {self.today}",
            "",
            "金额都折成人民币。本文件含持仓数量和金额，只留在本机，不要提交到 git。",
            "",
            f"- 总资产：{_money(p.total_cny)}",
            f"- 浮动盈亏：{pnl}" + (
                f"，其中持有期分红 {_money(p.dividend_cny, signed=True)}"
                if p.dividend_cny is not None else ""),
            f"- 现金：{_money(p.cash_cny)}（{_pct(p.cash_pct)}）",
        ]
        if p.cash:
            lines.append("- 现金明细：" + " · ".join(f"{c} {_money(v)}" for c, v in p.cash.items()))
        if rates:
            lines.append(f"- 汇率（兑人民币，新浪）：{rates}")
        lines += [
            "",
            "现价由程序从行情接口取（来源见表格最后一列）。盈亏 = 市值 − 成本 + 分红：成本按配置里的成本价，"
            "分红是 since（持有起始日）之后除息的税前现金分红 × 现在的数量，折人民币，"
            "来自东方财富、新浪（ETF）、雅虎财经（港股、美股）；不含已实现盈亏，不含送转股。",
            "",
            "| 代码 | 名称 | 动作 | 数量 | 币种 | 成本价 | 现价 | 现价日期 | 市值 | 分红 | 盈亏 | 盈亏% | 占比 | 现价来源 |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for position in p.positions:
            h = position.holding
            advice = self.parsed.advice.get(h.symbol)
            priced = position.price is not None
            lines.append("| " + " | ".join([
                h.symbol,
                h.name,
                self._status(advice),
                format_price(float(h.quantity)),
                h.currency,
                format_price(float(h.cost)),
                format_price(position.price) if priced else "—",
                position.price_date.isoformat() if priced else "—",
                _money(position.value_cny),
                _money(position.dividend_cny),
                _money(position.pnl_cny, signed=True),
                _signed_pct(position.pnl_pct),
                _pct(position.weight_pct),
                position.price_source if priced else "—",
            ]) + " |")
        notes = self._notes()
        no_since = _with_issue(p, NO_SINCE)
        if no_since:
            notes.append(
                "没有设置 since（持有起始日），分红没有计入盈亏：" + "、".join(no_since)
                + "。在 holdings.toml 顶部写 since = 2026-10-23（日期不加引号）即可")
        if notes:
            lines += ["", "## 提醒", *[f"- {n}" for n in notes]]
        lines += ["", "## 模型回复原文", "", raw.strip(), ""]
        return "\n".join(lines)


def _with_issue(portfolio: Portfolio, issue: str) -> List[str]:
    return [p.holding.name for p in portfolio.positions if p.dividend_issue == issue]


def _sections_text(head: str, sections: Dict[str, str]) -> str:
    blocks = [f"**{title}**\n{body.strip()}" for title, body in sections.items() if body.strip()]
    return "\n\n".join([head, *blocks])


def _weights(position: Position) -> str:
    if position.weight_pct is None:
        return "现价不可用"
    return f"占比 {_pct(position.weight_pct)} · 盈亏 {_signed_pct(position.pnl_pct)}"


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _signed_pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def _money(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+,.2f}" if signed else f"{value:,.2f}"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name
