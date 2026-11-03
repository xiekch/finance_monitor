from datetime import date, timedelta

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
    assert overseas_sina_code("^GSPC", "US") == "gb_$inx"
    assert overseas_sina_code("^DJI", "US") == "gb_$dji"
    assert overseas_sina_code("^NDX", "US") == "gb_$ndx"
    assert overseas_sina_code("^N225", "JP") == "b_NKY"

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
        today=date(2026, 10, 13),
    )
    assert us is not None
    assert us[0].close == 340.97
    assert round(us[1], 2) == 336.64


def test_index_quotes_require_a_recent_session_date():
    today = date(2026, 11, 2)
    frozen_spx = ["标普指数", "6643.70", "38.98", "0.59"]
    frozen_nikkei = ["日经指数", "44946.64", "-408.35", "-0.90"]
    assert overseas_quote("^GSPC", "US", frozen_spx, today=today) is None
    assert overseas_quote("^N225", "JP", frozen_nikkei, today=today) is None

    spx = overseas_quote(
        "^GSPC", "US",
        ["标普500指数", "7541.3999", "-0.51", "2026-11-03 05:51:02", "-38.6700",
         "7610.8301", "7662.2300", "7539.3799"],
        today=date(2026, 11, 3),
    )
    assert spx is not None
    assert spx[0].close == 7541.3999
    assert round(spx[1], 4) == 7580.0699

    ndx = overseas_quote(
        "^NDX", "US",
        ["纳斯达克100", "27989.8197", "-1.39", "2026-11-03 06:30:00", "-395.0255",
         "28561.1669", "28753.3931", "27967.4419"],
        today=date(2026, 11, 3),
    )
    assert ndx is not None
    assert round(ndx[1] - ndx[0].close, 4) == 395.0255

    nikkei = overseas_quote(
        "^N225", "JP",
        ["日经225指数", "63081.6400", "-208.47", "-0.33", "2:12 AM", "14:12:00",
         "2026-11-02", "14:30:02"],
        today=date(2026, 11, 3),
    )
    assert nikkei is not None
    assert nikkei[0].close == 63081.64
    assert round(nikkei[1], 2) == 63290.11

    kospi = overseas_quote(
        "^KS11", "KR",
        ["韩国KOSPI指数", "5668.3300", "-190.75", "-3.26", "2:27 AM", "14:27:00",
         "2026-11-03", "11:50:40"],
        today=date(2026, 11, 3),
    )
    assert kospi is not None
    assert round(kospi[1], 2) == 5859.08


def test_us_quote_older_than_four_days_is_dropped():
    today = date(2026, 11, 2)
    fields = ["苹果", "340.97", "1.29", "", "4.33", "338.215", "342.63", "337.6"]

    fresh = list(fields)
    fresh[3] = (today - timedelta(days=4)).isoformat()
    assert overseas_quote("AAPL", "US", fresh, today=today) is not None

    stale = list(fields)
    stale[3] = (today - timedelta(days=5)).isoformat()
    assert overseas_quote("AAPL", "US", stale, today=today) is None

    ahead = list(fields)
    ahead[3] = (today + timedelta(days=1)).isoformat()
    assert overseas_quote("AAPL", "US", ahead, today=today) is not None

    too_far = list(fields)
    too_far[3] = (today + timedelta(days=2)).isoformat()
    assert overseas_quote("AAPL", "US", too_far, today=today) is None


def test_futures_price_uses_latest_not_zero_prev_close():
    fields = parse_sina_body(_FUTURES)["nf_AU0"]
    price = price_from_fields("AU0", "FUT", fields)
    assert price is not None
    assert price.close == 906.080
    assert price.high == 908.720
    assert price.volume == 144845
