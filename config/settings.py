import os
from dotenv import load_dotenv

load_dotenv()

# API配置
API_CONFIG = {
    'itick': {
        'token': os.getenv('ITICK_TOKEN', 'YOUR_ITICK_TOKEN'),
        'base_url': 'https://api.itick.org'
    },
    'finage': {
        'api_key': os.getenv('FINAGE_API_KEY', 'YOUR_FINAGE_KEY'),
        'base_url': 'https://api.finage.co.uk'
    },
    'binance': {
        'base_url': 'https://api.binance.com',
        'websocket_url': 'wss://stream.binance.com:9443'
    }
}

# 企业微信配置
WECOM_CONFIG = {
    'webhook_url': os.getenv('WECOM_WEBHOOK_URL', '')
}

# 监控配置 - 完整的配置
MONITOR_CONFIG = {
    'minute': {
        'stocks': [
            {'name': '腾讯控股', 'symbol': '00700', 'market': 'HK', 'threshold': 1.5},
            {'name': '贵州茅台', 'symbol': '600519', 'market': 'SH', 'threshold': 1.5},
            {'name': '苹果', 'symbol': 'AAPL', 'market': 'US', 'threshold': 2.0},
            {'name': '特斯拉', 'symbol': 'TSLA', 'market': 'US', 'threshold': 2.0},
        ],
        'crypto': [
            {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'threshold': 3.0},
            {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'threshold': 3.0},
        ],
        'futures': [
            {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'threshold': 1.0},
            {'name': '原油主力', 'symbol': 'CL', 'market': 'FUT', 'threshold': 1.5},
        ]
    },
    'daily': {
        'stocks': [
            {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'threshold': 3.0},
            {'name': '创业板指', 'symbol': '399006', 'market': 'SZ', 'threshold': 4.0},
            {'name': '纳斯达克', 'symbol': 'NDX', 'market': 'US', 'threshold': 2.5},
        ],
        'crypto': [
            {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'threshold': 8.0},
            {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'threshold': 10.0},
        ],
        'futures': [
            {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'threshold': 2.5},
            {'name': '原油主力', 'symbol': 'CL', 'market': 'FUT', 'threshold': 3.0},
        ]
    },
    'weekly': {
        'stocks': [
            {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'threshold': 5.0},
            {'name': '纳斯达克', 'symbol': 'NDX', 'market': 'US', 'threshold': 4.0},
        ],
        'crypto': [
            {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'threshold': 15.0},
            {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'threshold': 18.0},
        ],
        'futures': [
            {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'threshold': 4.0},
        ]
    }
}

# 任务调度配置
TASK_CONFIG = {
    'minute_interval': 1,  # 分钟级任务间隔
    'daily_time': '16:05',  # 日频任务执行时间
    'weekly_time': '09:00'   # 周频任务执行时间
}

# 数据库配置
DATABASE_CONFIG = {
    'path': 'market_data.db',
    'backup_interval_hours': 24
}

REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', 'localhost'),
    'port': int(os.getenv('REDIS_PORT', 6379)),
    'db': int(os.getenv('REDIS_DB', 0)),
    'password': os.getenv('REDIS_PASSWORD') or None,
    'decode_responses': True
}