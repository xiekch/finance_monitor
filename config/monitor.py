"""监控标的配置。

按 asset_type 分组，frequency 在每条 item 内；同标的不同频次各一条。
"""

MONITOR_CONFIG = {
    'stocks': [
        # minute
        {'name': '腾讯控股', 'symbol': '00700', 'market': 'HK', 'frequency': 'minute', 'threshold': 1.5},
        {'name': '贵州茅台', 'symbol': '600519', 'market': 'SH', 'frequency': 'minute', 'threshold': 1.5},
        {'name': '苹果', 'symbol': 'AAPL', 'market': 'US', 'frequency': 'minute', 'threshold': 2.0},
        {'name': '特斯拉', 'symbol': 'TSLA', 'market': 'US', 'frequency': 'minute', 'threshold': 2.0},
        # daily
        {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'frequency': 'daily', 'threshold': 3.0},
        {'name': '创业板指', 'symbol': '399006', 'market': 'SZ', 'frequency': 'daily', 'threshold': 4.0},
        {'name': '纳斯达克', 'symbol': '^NDX', 'market': 'US', 'frequency': 'daily', 'threshold': 1},
        {'name': '苹果', 'symbol': 'AAPL', 'market': 'US', 'frequency': 'daily', 'threshold': 1.5},
        {'name': '特斯拉', 'symbol': 'TSLA', 'market': 'US', 'frequency': 'daily', 'threshold': 2.0},
        # weekly
        {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'frequency': 'weekly', 'threshold': 5.0},
        {'name': '纳斯达克', 'symbol': '^NDX', 'market': 'US', 'frequency': 'weekly', 'threshold': 4.0},
    ],
    'crypto': [
        # minute
        {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'frequency': 'minute', 'threshold': 3.0},
        {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'frequency': 'minute', 'threshold': 3.0},
        # daily
        {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'frequency': 'daily', 'threshold': 2.0},
        {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'frequency': 'daily', 'threshold': 3.0},
        # weekly
        {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'frequency': 'weekly', 'threshold': 15.0},
        {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'frequency': 'weekly', 'threshold': 18.0},
    ],
    'futures': [
        # minute
        {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'frequency': 'minute', 'threshold': 1.0},
        {'name': '原油主力', 'symbol': 'SC0', 'market': 'FUT', 'frequency': 'minute', 'threshold': 1.5},
        # daily
        {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'frequency': 'daily', 'threshold': 2.5},
        {'name': '原油主力', 'symbol': 'SC0', 'market': 'FUT', 'frequency': 'daily', 'threshold': 3.0},
        # weekly
        {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'frequency': 'weekly', 'threshold': 4.0},
    ],
}
