import os
from dotenv import load_dotenv

load_dotenv()

PROXY = True
PROXY_URL = "http://127.0.0.1:7897" 
if PROXY:
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'

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
            {'name': '纳斯达克', 'symbol': '^NDX', 'market': 'US', 'threshold': 1},
            {'name': '苹果', 'symbol': 'AAPL', 'market': 'US', 'threshold': 1.5},
            {'name': '特斯拉', 'symbol': 'TSLA', 'market': 'US', 'threshold': 2.0},   
        ],
        'crypto': [
            {'name': 'Bitcoin', 'symbol': 'BTCUSDT', 'market': 'CRYPTO', 'threshold': 2.0},
            {'name': 'Ethereum', 'symbol': 'ETHUSDT', 'market': 'CRYPTO', 'threshold': 3.0},
        ],
        'futures': [
            {'name': '黄金主力', 'symbol': 'AU0', 'market': 'FUT', 'threshold': 2.5},
            {'name': '原油主力', 'symbol': 'CL', 'market': 'FUT', 'threshold': 3.0},
        ]
    },
    'weekly': {
        'stocks': [
            {'name': '沪深300', 'symbol': '000300', 'market': 'SH', 'threshold': 5.0},
            {'name': '纳斯达克', 'symbol': '^NDX', 'market': 'US', 'threshold': 4.0},
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

# Producer 调度配置
# 与 PRODUCER_REGISTRY 的 key 对应；value 描述触发器类型与参数。
# - type: 'cron' | 'interval'，对应 APScheduler 的 CronTrigger / IntervalTrigger
# - kwargs: 传给对应 trigger 构造函数的参数
# - None: 表示该 producer 无定时调度（只能 run_immediately / ignore_schedule 使用）
# 所有时间为本机时区（一般是北京时间）。
PRODUCER_SCHEDULE = {
    # A 股
    'astock_minute': {
        'type': 'cron',
        # 交易时段 9:30-15:00 简化为 9-14 整点段每 5 分钟，工作日
        'kwargs': {'hour': '9-14', 'minute': '*/5', 'day_of_week': 'mon-fri'},
    },
    'astock_daily': {
        'type': 'cron',
        # 收盘后 15:30，工作日
        'kwargs': {'hour': 15, 'minute': 30, 'day_of_week': 'mon-fri'},
    },
    'astock_weekly': {
        'type': 'cron',
        # 每周六早 8 点
        'kwargs': {'day_of_week': 'sat', 'hour': 8, 'minute': 0},
    },
    # 美股
    'usstock_minute': {
        'type': 'cron',
        # 北京时间晚 9 点到次日凌晨 4 点（美东 9:30-16:00），每 5 分钟
        'kwargs': {'hour': '21-23,0-4', 'minute': '*/5', 'day_of_week': 'mon-fri'},
    },
    'usstock_daily': {
        'type': 'cron',
        # 北京时间凌晨 5 点，工作日
        'kwargs': {'hour': 5, 'minute': 0, 'second': 0, 'day_of_week': 'mon-fri'},
    },
    'usstock_weekly': {
        'type': 'cron',
        # 每周一北京时间早 6 点
        'kwargs': {'day_of_week': 'mon', 'hour': 6, 'minute': 0, 'second': 0},
    },
    # 加密货币（24/7 市场）
    'crypto_minute': {
        'type': 'cron',
        'kwargs': {'minute': '*/5'},
    },
    'crypto_daily': {
        'type': 'cron',
        'kwargs': {'hour': 5, 'minute': 0, 'second': 0},
    },
    'crypto_weekly': {
        'type': 'cron',
        'kwargs': {'day_of_week': 'mon', 'hour': 5, 'minute': 0},
    },
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