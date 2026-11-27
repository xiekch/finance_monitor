"""分钟级盯盘的股票标的：MONITOR_CONFIG 里的大盘指数 + config/holdings.toml 里的股票持仓。

每次调用都重新读持仓文件，改持仓不用重启。持仓文件不进 git，所以持仓标的
只存在内存和本机日志里，不写进 config/monitor.py。

盯盘有两个判据，任一超过阈值就告警：
- 相对昨收：现价相对昨天收盘价的涨跌幅（prev_close_threshold）
- 相对 WINDOW_MINUTES 分钟前：现价相对半小时前价格的涨跌幅（threshold）
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

from config.holdings import HOLDINGS_FILE
from config.monitor import MONITOR_CONFIG
from models.holdings import HoldingsConfigError
from storage.holdings_store import load_holdings_config

# 盯盘只看股票（含场内 ETF）；加密货币和期货的分钟级仍在 config/monitor.py。
MINUTE_STOCK_MARKETS = ("SH", "SZ", "HK", "US")

# 「相对 N 分钟前」的 N。要改成 1 小时就写 60。
WINDOW_MINUTES = 30

# 持仓里没写阈值时的默认值（%）。
DEFAULT_WINDOW_THRESHOLD = {"SH": 1.5, "SZ": 1.5, "HK": 1.5, "US": 2.0}
DEFAULT_PREV_CLOSE_THRESHOLD = {"SH": 3.0, "SZ": 3.0, "HK": 3.0, "US": 4.0}


def minute_stock_targets(path: Optional[Path] = None) -> List[dict]:
    """分钟级盯盘的股票标的：MONITOR_CONFIG 里的大盘指数 + 持仓中的股票。

    格式同 MONITOR_CONFIG['stocks'] 的一条（frequency 固定为 minute）。threshold 是相对
    WINDOW_MINUTES 分钟前的阈值，prev_close_threshold 是相对昨收的阈值。同一个 (代码, 市场)
    持仓里的设置优先。持仓文件读不到或写错时只剩大盘指数，并记 error，不影响其它 task。
    """
    targets: Dict[tuple, dict] = {}
    for asset in MONITOR_CONFIG.get("stocks", []):
        market = asset.get("market", "")
        if asset["frequency"] != "minute" or market not in MINUTE_STOCK_MARKETS:
            continue
        targets[(asset["symbol"], market)] = {
            **asset,
            "prev_close_threshold": asset.get(
                "prev_close_threshold", DEFAULT_PREV_CLOSE_THRESHOLD[market]),
        }
    for target in _holding_targets(path):
        targets[(target["symbol"], target["market"])] = target
    return list(targets.values())


def _holding_targets(path: Optional[Path]) -> List[dict]:
    try:
        config = load_holdings_config(path or HOLDINGS_FILE)
    except HoldingsConfigError as e:
        logging.error(f"[minute_targets] 读不到持仓，本轮只盯大盘指数: {e}")
        return []

    targets = []
    for holding in config.holdings:
        if holding.market not in MINUTE_STOCK_MARKETS:
            continue
        window = holding.alert_window_pct
        if window is None:
            window = DEFAULT_WINDOW_THRESHOLD[holding.market]
        day = holding.alert_day_pct
        if day is None:
            day = DEFAULT_PREV_CLOSE_THRESHOLD[holding.market]
        targets.append({
            "name": holding.name,
            "symbol": holding.symbol,
            "market": holding.market,
            "frequency": "minute",
            "threshold": window,
            "prev_close_threshold": day,
        })
    return targets
