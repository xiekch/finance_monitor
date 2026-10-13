import pandas as pd

from fetchers.us_stock_yf_fetcher import bars_from_history, split_download_frame


def test_split_download_groups_by_ticker():
    frame = pd.DataFrame(
        {
            ("AAPL", "Open"): [1.0, 2.0],
            ("AAPL", "High"): [1.0, 2.0],
            ("AAPL", "Low"): [1.0, 2.0],
            ("AAPL", "Close"): [1.0, 2.0],
            ("AAPL", "Volume"): [10, 11],
            ("0700.HK", "Open"): [3.0, 4.0],
            ("0700.HK", "High"): [3.0, 4.0],
            ("0700.HK", "Low"): [3.0, 4.0],
            ("0700.HK", "Close"): [3.0, 4.0],
            ("0700.HK", "Volume"): [20, 21],
        },
        index=pd.to_datetime(["2026-10-10", "2026-10-13"]),
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    split = split_download_frame(frame, ["AAPL", "0700.HK"])
    assert list(split) == ["AAPL", "0700.HK"]
    bars = bars_from_history(split["AAPL"], "AAPL", "US", "1d")
    assert [bar.close for bar in bars] == [1.0, 2.0]
    assert bars[-1].timestamp.tzinfo is None
