from fetchers.sina_quote import (
    overseas_quote,
    overseas_sina_code,
    parse_sina_body,
    price_from_fields,
    sina_code,
)


_ASHARE = (
    'var hq_str_sh600519="贵州茅台,1287.000,1288.000,1268.430,1288.480,1268.110,1,2,2023243,0";\n'
    'var hq_str_sh000001="";'
)
_FUTURES = (
    'var hq_str_nf_AU0="黄金连续,141736,901.000,908.720,897.980,0.000,'
    '906.080,906.100,906.080,0.000,907.780,5,4,229175.000,144845,沪,黄金,2026-10-13";'
)


def test_sina_code():
    assert sina_code("600519", "SH") == "sh600519"
    assert sina_code("399006", "SZ") == "sz399006"
    assert sina_code("AU0", "FUT") == "nf_AU0"


def test_parse_skips_empty_quote():
    parsed = parse_sina_body(_ASHARE)
    assert list(parsed) == ["sh600519"]
    assert parsed["sh600519"][3] == "1268.430"


def test_ashare_price_uses_latest():
    fields = parse_sina_body(_ASHARE)["sh600519"]
    price = price_from_fields("600519", "SH", fields)
    assert price is not None
    assert price.close == 1268.430
    assert price.open == 1287.0
    assert price.volume == 2023243
    assert price.market == "SH"


def test_overseas_codes_and_prev_close():
    assert overseas_sina_code("00700", "HK") == "hk00700"
    assert overseas_sina_code("AAPL", "US") == "gb_aapl"
    assert overseas_sina_code("^KS11", "KR") == "b_KOSPI"

    hk = overseas_quote(
        "00700", "HK",
        ["TENCENT", "腾讯控股", "421", "425.8", "425.6", "419.8", "424.2"],
    )
    assert hk is not None
    assert hk[0].close == 424.2
    assert hk[1] == 425.8

    us = overseas_quote(
        "AAPL", "US",
        ["苹果", "340.97", "1.29", "2026-10-13", "4.33", "338.215", "342.63", "337.6"],
    )
    assert us is not None
    assert us[0].close == 340.97
    assert round(us[1], 2) == 336.64


def test_futures_price_uses_latest_not_zero_prev_close():
    fields = parse_sina_body(_FUTURES)["nf_AU0"]
    price = price_from_fields("AU0", "FUT", fields)
    assert price is not None
    assert price.close == 906.080
    assert price.high == 908.720
    assert price.volume == 144845
