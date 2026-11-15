import asyncio
from datetime import date

import fetchers.holding_quotes as hq
from fetchers.sina_quote import parse_sina_body
from models.holdings import Holding

TODAY = date(2026, 11, 15)

# 2026-11-15 实际抓到的报价，只保留用得到的字段位置
_A = "恒生科技ETF华夏,0.488,0.491,0.478,0.492,0.476,0.477,0.478,4435971621,2148016800.000" + ",0" * 20 + ",2026-11-13,15:34:59,00,"
_HK = "TENCENT,腾讯控股,393.000,398.800,395.200,385.600,387.000,-11.800,-2.959,387.00000,387.00000,11502009329,29581539,0.000,0.000,683.000,372.200,2026/11/13,16:07"
_US = ("英伟达,162.8500,-2.01,2026-11-14 09:14:56,-3.3400,169.9050,170.0000,158.3900,243.3700,158.3900,365796552,299389000"
       + ",0" * 12 + ",Nov 13 07:59PM EST,Nov 13 04:00PM EST,166.19,2000,1,2026,0,0,0,0,0,0")
_FUT = "黄金连续,023000,838.760,843.060,835.360,0.000,838.700,839.660,839.060,0.000,840.960,1,2,3,4,5,6,2026-11-14,1"
_BODY = (
    f'var hq_str_sh513180="{_A}";\n'
    f'var hq_str_hk00700="{_HK}";\n'
    f'var hq_str_gb_nvda="{_US}";\n'
    f'var hq_str_nf_AU0="{_FUT}";\n'
    'var hq_str_sz000001="";\n'
)
_FIELDS = parse_sina_body(_BODY)


def _holding(symbol, market):
    return Holding(symbol=symbol, market=market, name=symbol, quantity=1, cost=1)


def test_sina_codes():
    assert hq.sina_code_for(_holding("513180", "SH")) == "sh513180"
    assert hq.sina_code_for(_holding("000333", "SZ")) == "sz000333"
    assert hq.sina_code_for(_holding("700", "HK")) == "hk00700"
    assert hq.sina_code_for(_holding("NVDA", "US")) == "gb_nvda"
    assert hq.sina_code_for(_holding("au0", "FUT")) == "nf_AU0"
    assert hq.sina_code_for(_holding("BTCUSDT", "CRYPTO")) is None


def test_quote_from_fields_per_market():
    a = hq.quote_from_fields("SH", _FIELDS["sh513180"], TODAY)
    assert (a.price, a.day, a.source) == (0.478, date(2026, 11, 13), "新浪行情")
    hk = hq.quote_from_fields("HK", _FIELDS["hk00700"], TODAY)
    assert (hk.price, hk.day) == (387.0, date(2026, 11, 13))
    # 美股用美东的交易日，不用新浪更新时间里的北京日期
    us = hq.quote_from_fields("US", _FIELDS["gb_nvda"], TODAY)
    assert (us.price, us.day) == (162.85, date(2026, 11, 13))
    fut = hq.quote_from_fields("FUT", _FIELDS["nf_AU0"], TODAY)
    assert (fut.price, fut.day) == (839.06, date(2026, 11, 14))


def test_quote_falls_back_to_previous_close_before_open():
    fields = list(_FIELDS["sh513180"])
    fields[3] = "0.000"   # 集合竞价时现价是 0
    assert hq.quote_from_fields("SH", fields, TODAY).price == 0.491


def test_quote_rejects_stale_missing_or_broken():
    assert hq.quote_from_fields("SH", _FIELDS["sh513180"], date(2026, 11, 24)) is None   # 11 天前
    assert hq.quote_from_fields("SH", _FIELDS["sh513180"], date(2026, 11, 23)) is not None
    assert hq.quote_from_fields("SH", None, TODAY) is None
    assert hq.quote_from_fields("SH", ["恒生科技ETF华夏", "0.488"], TODAY) is None
    no_date = list(_FIELDS["sh513180"])
    no_date[30] = ""
    assert hq.quote_from_fields("SH", no_date, TODAY) is None
    zero = list(_FIELDS["hk00700"])
    zero[6] = zero[3] = "0"
    assert hq.quote_from_fields("HK", zero, TODAY) is None
    assert hq.quote_from_fields("CRYPTO", _FIELDS["sh513180"], TODAY) is None


def test_us_date_falls_back_to_update_time():
    fields = list(_FIELDS["gb_nvda"])
    fields[25] = ""
    assert hq.quote_from_fields("US", fields, TODAY).day == date(2026, 11, 14)


def test_crypto_pair():
    assert hq.crypto_pair("btcusdt") == "BTCUSDT"
    assert hq.crypto_pair("ETH") == "ETHUSDT"
    assert hq.crypto_pair("SOL-USD") == "SOLUSDT"


def test_fetch_holding_quotes(monkeypatch):
    asked = []

    async def fake_sina(codes):
        asked.append(list(codes))
        return {k: v for k, v in _FIELDS.items() if k in codes}

    def fake_crypto(pair):
        if pair == "BTCUSDT":
            return 64740.49
        raise OSError("连接被重置")

    monkeypatch.setattr(hq, "fetch_sina_quotes", fake_sina)
    monkeypatch.setattr(hq, "_binance_price", fake_crypto)
    holdings = [
        _holding("513180", "SH"), _holding("00700", "HK"), _holding("NVDA", "US"),
        _holding("AU0", "FUT"), _holding("000001", "SZ"),
        _holding("BTCUSDT", "CRYPTO"), _holding("ETH", "CRYPTO"),
    ]
    quotes = asyncio.run(hq.fetch_holding_quotes(holdings, TODAY))
    assert asked == [["sh513180", "hk00700", "gb_nvda", "nf_AU0", "sz000001"]]
    # 没有报价的 000001 和取价失败的 ETH 不在结果里
    assert list(quotes) == ["513180", "00700", "NVDA", "AU0", "BTCUSDT"]
    assert quotes["BTCUSDT"].price == 64740.49
    assert quotes["BTCUSDT"].day == TODAY and quotes["BTCUSDT"].source == "币安"


def test_fetch_holding_quotes_survives_sina_failure(monkeypatch):
    async def broken(codes):
        raise OSError("SSL EOF")

    monkeypatch.setattr(hq, "fetch_sina_quotes", broken)
    monkeypatch.setattr(hq, "_binance_price", lambda pair: 64740.49)
    quotes = asyncio.run(hq.fetch_holding_quotes(
        [_holding("513180", "SH"), _holding("BTCUSDT", "CRYPTO")], TODAY))
    assert list(quotes) == ["BTCUSDT"]

    asked = []

    async def never(codes):
        asked.append(codes)
        return {}

    monkeypatch.setattr(hq, "fetch_sina_quotes", never)
    assert asyncio.run(hq.fetch_holding_quotes([], TODAY)) == {}
    assert asked == []
