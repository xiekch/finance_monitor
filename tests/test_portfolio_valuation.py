from datetime import date

import pytest

from analyzers.portfolio import (
    FETCH_FAILED,
    NO_SINCE,
    Dividend,
    PriceQuote,
    apply_prices,
    build_portfolio,
)
from models.holdings import parse_holdings_config

FX = {"CNY": 1.0, "USD": 7.0, "HKD": 0.9}
DAY = date(2026, 11, 13)


def _config(rules=None):
    return parse_holdings_config({
        "cash": {"CNY": 20000, "USD": 1000},
        "rules": rules or {},
        "holdings": [
            # 成本 100 × 500 = 50000 CNY
            {"symbol": "600519", "market": "SH", "name": "贵州茅台", "quantity": 100, "cost": 500},
            # 成本 100 × 100 × 0.9 = 9000 CNY
            {"symbol": "00700", "market": "HK", "name": "腾讯控股", "quantity": 100, "cost": 100},
            # 成本 20 × 100 × 7 = 14000 CNY
            {"symbol": "NVDA", "market": "US", "name": "英伟达", "quantity": 20, "cost": 100},
        ],
    })


def _quote(price):
    return PriceQuote(price=price, day=DAY, source="新浪行情")


def test_cost_weights_across_currencies():
    portfolio = build_portfolio(_config(), FX)
    # 现金 20000 + 1000 × 7 = 27000；总成本 50000 + 9000 + 14000 + 27000 = 100000
    assert portfolio.cash_cny == 27000
    assert portfolio.cost_total_cny == 100000
    assert [p.cost_cny for p in portfolio.positions] == [50000, 9000, 14000]
    assert [p.cost_weight_pct for p in portfolio.positions] == pytest.approx([50, 9, 14])
    assert portfolio.cash_cost_weight_pct == pytest.approx(27)
    assert portfolio.total_cny is None and portfolio.pnl_pct is None


def test_missing_fx_rate_is_an_error():
    with pytest.raises(ValueError, match="HKD"):
        build_portfolio(_config(), {"CNY": 1.0, "USD": 7.0})


def test_valuation_with_prices():
    portfolio = build_portfolio(_config(), FX)
    apply_prices(portfolio, {
        "600519": _quote(450),   # 45000，亏 5000
        "00700": _quote(200),    # 200 × 100 × 0.9 = 18000，赚 9000
        "NVDA": _quote(150),     # 150 × 20 × 7 = 21000，赚 7000
    })
    maotai, tencent, nvda = portfolio.positions
    assert (maotai.value_cny, tencent.value_cny, nvda.value_cny) == (45000, 18000, 21000)
    assert maotai.pnl_cny == -5000 and maotai.pnl_pct == pytest.approx(-10)
    assert tencent.pnl_pct == pytest.approx(100)
    assert maotai.price_date == DAY and maotai.price_source == "新浪行情"
    # 总资产 45000 + 18000 + 21000 + 27000 = 111000
    assert portfolio.total_cny == 111000
    assert maotai.weight_pct == pytest.approx(45000 / 111000 * 100)
    assert portfolio.cash_pct == pytest.approx(27000 / 111000 * 100)
    assert portfolio.pnl_cny == 11000
    assert portfolio.pnl_pct == pytest.approx(11000 / 73000 * 100)
    assert portfolio.currency_pct == pytest.approx({
        "CNY": 65000 / 111000 * 100,
        "USD": 28000 / 111000 * 100,
        "HKD": 18000 / 111000 * 100,
    })
    assert portfolio.breaches == [] and portfolio.breached_symbols == set()


def test_unpriced_position_is_left_out_not_valued_at_zero():
    portfolio = build_portfolio(_config(), FX)
    apply_prices(portfolio, {"600519": _quote(450), "NVDA": _quote(150)})
    tencent = portfolio.positions[1]
    assert tencent.value_cny is None and tencent.weight_pct is None and tencent.pnl_pct is None
    assert portfolio.total_cny == 45000 + 21000 + 27000
    assert portfolio.pnl_cny == 2000
    assert portfolio.pnl_pct == pytest.approx(2000 / 64000 * 100)
    assert [p.holding.symbol for p in portfolio.unpriced] == ["00700"]


def test_no_prices_at_all():
    portfolio = build_portfolio(_config(), FX)
    apply_prices(portfolio, {})
    assert portfolio.total_cny == 27000
    assert portfolio.pnl_cny is None and portfolio.pnl_pct is None
    assert len(portfolio.unpriced) == 3


def test_futures_multiplier():
    config = parse_holdings_config({"holdings": [
        {"symbol": "CU0", "market": "FUT", "name": "沪铜主力", "quantity": 2, "cost": 80000,
         "multiplier": 5},
    ]})
    portfolio = build_portfolio(config, {"CNY": 1.0})
    assert portfolio.positions[0].cost_cny == 800000
    apply_prices(portfolio, {"CU0": _quote(81000)})
    assert portfolio.positions[0].value_cny == 810000
    assert portfolio.positions[0].pnl_cny == 10000


def _dividend_config():
    since = date(2026, 10, 23)
    return parse_holdings_config({
        "since": since,
        "holdings": [
            # 成本 500 × 100 = 50000
            {"symbol": "600519", "market": "SH", "name": "贵州茅台", "quantity": 100, "cost": 500},
            # 成本 100 × 100 × 0.9 = 9000
            {"symbol": "00700", "market": "HK", "name": "腾讯控股", "quantity": 100, "cost": 100},
            {"symbol": "NVDA", "market": "US", "name": "英伟达", "quantity": 20, "cost": 100,
             "since": date(2026, 11, 20)},
            {"symbol": "BTCUSDT", "market": "CRYPTO", "name": "BTC", "quantity": 1, "cost": 100},
            {"symbol": "000333", "market": "SZ", "name": "美的集团", "quantity": 10, "cost": 10},
        ],
    })


def test_dividends_count_only_ex_dates_in_holding_window_and_convert_currency():
    config = _dividend_config()
    portfolio = build_portfolio(config, FX)
    quotes = {"600519": _quote(500), "00700": _quote(100), "NVDA": _quote(100),
              "BTCUSDT": _quote(100), "000333": _quote(10)}
    dividends = {
        "600519": [
            Dividend(date(2026, 10, 23), 99),    # 除息日就是 since：不算
            Dividend(date(2026, 10, 24), 20),    # 算：20 × 100 = 2000
            Dividend(date(2026, 11, 14), 8),     # 算：8 × 100 = 800
            Dividend(date(2026, 11, 16), 50),    # 还没除息：不算
        ],
        "00700": [Dividend(date(2026, 11, 1), 5)],            # 5 × 100 × 0.9 = 450
        "NVDA": [Dividend(date(2026, 11, 12), 1),             # 在自己的 since 之前：不算
                 Dividend(date(2026, 11, 21), 0.5)],          # 0.5 × 20 × 7 = 70
        "000333": [],                                         # 取到了，没有分红
    }
    apply_prices(portfolio, quotes, dividends=dividends, today=date(2026, 11, 14))
    maotai, tencent, nvda, btc, midea = portfolio.positions
    assert maotai.dividend_cny == pytest.approx(2800) and maotai.dividend_issue == ""
    assert tencent.dividend_cny == pytest.approx(450)
    assert nvda.dividend_cny == 0   # 11 月 21 日在 today 之后
    assert btc.dividend_cny == 0 and midea.dividend_cny == 0
    # 盈亏 = 价差 + 分红；价格没动，盈亏就是分红
    assert maotai.pnl_cny == pytest.approx(2800)
    assert maotai.pnl_pct == pytest.approx(2800 / 50000 * 100)
    assert portfolio.dividend_cny == pytest.approx(3250)
    assert portfolio.pnl_cny == pytest.approx(3250)


def test_dividend_in_foreign_currency_uses_fx():
    config = _dividend_config()
    portfolio = build_portfolio(config, FX)
    apply_prices(portfolio, {"NVDA": _quote(100)},
                 dividends={"NVDA": [Dividend(date(2026, 11, 21), 0.5)]}, today=date(2026, 11, 23))
    assert portfolio.positions[2].dividend_cny == pytest.approx(0.5 * 20 * 7)


def test_dividend_unknown_is_not_counted_as_zero():
    config = parse_holdings_config({"holdings": [
        {"symbol": "600519", "market": "SH", "name": "贵州茅台", "quantity": 100, "cost": 500,
         "since": date(2026, 10, 23)},
        {"symbol": "000333", "market": "SZ", "name": "美的集团", "quantity": 10, "cost": 10},
    ]})
    portfolio = build_portfolio(config, {})
    apply_prices(portfolio, {"600519": _quote(510), "000333": _quote(11)},
                 dividends={}, today=date(2026, 11, 23))
    maotai, midea = portfolio.positions
    assert maotai.dividend_cny is None and maotai.dividend_issue == FETCH_FAILED
    assert midea.dividend_cny is None and midea.dividend_issue == NO_SINCE
    # 盈亏仍然是价差，不因为分红没取到而丢掉
    assert maotai.pnl_cny == 1000 and midea.pnl_cny == 10
    assert portfolio.dividend_cny == 0


def test_without_dividend_data_pnl_is_price_only():
    portfolio = build_portfolio(_dividend_config(), FX)
    apply_prices(portfolio, {"600519": _quote(510)})
    assert portfolio.positions[0].pnl_cny == 1000
    assert portfolio.positions[0].dividend_cny is None and portfolio.dividend_cny is None


def test_rule_breaches():
    rules = {"max_position_pct": 30, "min_cash_pct": 30}
    config = _config(rules)
    portfolio = build_portfolio(config, FX)
    apply_prices(portfolio, {
        "600519": _quote(450), "00700": _quote(200), "NVDA": _quote(150),
    }, config.rules)
    assert portfolio.breached_symbols == {"600519"}
    assert len(portfolio.breaches) == 2
    assert "贵州茅台" in portfolio.breaches[0] and "30" in portfolio.breaches[0]
    assert "现金" in portfolio.breaches[1]


def test_weight_exactly_on_the_limit_is_not_a_breach():
    # 18000 / 45000 * 100 在浮点里是 40.00000000000001
    config = parse_holdings_config({
        "cash": {"CNY": 27000},
        "rules": {"max_position_pct": 40, "min_cash_pct": 60},
        "holdings": [{"symbol": "600519", "market": "SH", "name": "贵州茅台",
                      "quantity": 100, "cost": 100}],
    })
    portfolio = build_portfolio(config, {})
    apply_prices(portfolio, {"600519": PriceQuote(180.0, date(2026, 11, 13))},
                 config.rules)
    assert portfolio.breaches == [] and not portfolio.cash_below_min
