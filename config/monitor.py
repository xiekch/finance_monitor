"""监控标的配置。

按 asset_type 分组，frequency 在每条 item 内；同标的不同频次各一条。
"""

MONITOR_CONFIG = {
    'stocks': [
        # minute
        {'name': '腾讯控股', 'symbol': '00700', 'market': 'HK', 'frequency': 'minute', 'threshold': 1.5},
        {'name': '贵州茅台', 'symbol': '600519', 'market': 'SH', 'frequency': 'minute', 'threshold': 1.5},
        {'name': '宁德时代', 'symbol': '300750', 'market': 'SZ', 'frequency': 'minute', 'threshold': 2.0},
        {'name': '苹果', 'symbol': 'AAPL', 'market': 'US', 'frequency': 'minute', 'threshold': 2.0},
        {'name': '特斯拉', 'symbol': 'TSLA', 'market': 'US', 'frequency': 'minute', 'threshold': 2.0},
        {'name': '英伟达', 'symbol': 'NVDA', 'market': 'US', 'frequency': 'minute', 'threshold': 2.5},
        {'name': '微软', 'symbol': 'MSFT', 'market': 'US', 'frequency': 'minute', 'threshold': 2.0},
        # daily（A 股日/周线仅指数，见 AStockFetcher）
        {'name': '上证指数', 'symbol': '000001', 'market': 'SH', 'frequency': 'daily', 'threshold': 2.5},
        {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'frequency': 'daily', 'threshold': 3.0},
        {'name': '深证成指', 'symbol': '399001', 'market': 'SZ', 'frequency': 'daily', 'threshold': 3.0},
        {'name': '创业板指', 'symbol': '399006', 'market': 'SZ', 'frequency': 'daily', 'threshold': 4.0},
        {'name': '科创50', 'symbol': '000688', 'market': 'SH', 'frequency': 'daily', 'threshold': 4.0},
        {'name': '标普500', 'symbol': '^GSPC', 'market': 'US', 'frequency': 'daily', 'threshold': 1.0},
        {'name': '道琼斯', 'symbol': '^DJI', 'market': 'US', 'frequency': 'daily', 'threshold': 1.0},
        {'name': '纳斯达克', 'symbol': '^NDX', 'market': 'US', 'frequency': 'daily', 'threshold': 1.0},
        {'name': '苹果', 'symbol': 'AAPL', 'market': 'US', 'frequency': 'daily', 'threshold': 1.5},
        {'name': '特斯拉', 'symbol': 'TSLA', 'market': 'US', 'frequency': 'daily', 'threshold': 2.0},
        {'name': '英伟达', 'symbol': 'NVDA', 'market': 'US', 'frequency': 'daily', 'threshold': 2.5},
        {'name': '微软', 'symbol': 'MSFT', 'market': 'US', 'frequency': 'daily', 'threshold': 1.5},
        {'name': '日经225', 'symbol': '^N225', 'market': 'JP', 'frequency': 'daily', 'threshold': 1.5},
        {'name': '韩国综指', 'symbol': '^KS11', 'market': 'KR', 'frequency': 'daily', 'threshold': 1.5},
        # weekly
        {'name': '上证指数', 'symbol': '000001', 'market': 'SH', 'frequency': 'weekly', 'threshold': 5.0},
        {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'frequency': 'weekly', 'threshold': 5.0},
        {'name': '标普500', 'symbol': '^GSPC', 'market': 'US', 'frequency': 'weekly', 'threshold': 3.0},
        {'name': '纳斯达克', 'symbol': '^NDX', 'market': 'US', 'frequency': 'weekly', 'threshold': 4.0},
        {'name': '日经225', 'symbol': '^N225', 'market': 'JP', 'frequency': 'weekly', 'threshold': 4.0},
        {'name': '韩国综指', 'symbol': '^KS11', 'market': 'KR', 'frequency': 'weekly', 'threshold': 4.0},
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
        {'name': '白银主力', 'symbol': 'AG0', 'market': 'FUT', 'frequency': 'minute', 'threshold': 1.5},
        {'name': '原油主力', 'symbol': 'SC0', 'market': 'FUT', 'frequency': 'minute', 'threshold': 1.5},
        {'name': '沪铜主力', 'symbol': 'CU0', 'market': 'FUT', 'frequency': 'minute', 'threshold': 1.5},
        # daily
        {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'frequency': 'daily', 'threshold': 2.5},
        {'name': '白银主力', 'symbol': 'AG0', 'market': 'FUT', 'frequency': 'daily', 'threshold': 3.0},
        {'name': '原油主力', 'symbol': 'SC0', 'market': 'FUT', 'frequency': 'daily', 'threshold': 3.0},
        {'name': '沪铜主力', 'symbol': 'CU0', 'market': 'FUT', 'frequency': 'daily', 'threshold': 3.0},
        # weekly
        {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'frequency': 'weekly', 'threshold': 4.0},
    ],
}
