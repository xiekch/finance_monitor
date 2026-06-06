import os
from dotenv import load_dotenv

load_dotenv()

PROXY = False
PROXY_URL = "http://127.0.0.1:7897"
if PROXY:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
else:
    # 清掉 shell / .env / 上次跑 PROXY=True 残留的代理 env，否则 aiohttp、
    # yfinance(curl_cffi)、requests 都会偷偷走 env 里的代理 → 连不上 7897
    for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ.pop(_k, None)

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
        # 大陆直连 api.binance.com 会被 RST；data-api.binance.vision
        # 是 Binance 官方公开行情镜像，无需 key、通常无地理封锁
        'base_url': 'https://data-api.binance.vision',
        'websocket_url': 'wss://stream.binance.com:9443'
    }
}

# 企业微信配置（支持多个 webhook，逗号分隔）
WECOM_CONFIG = {
    'webhook_urls': [
        u.strip() for u in os.getenv('WECOM_WEBHOOK_URL', '').split(',') if u.strip()
    ],
}

# 监控配置
# 按 asset_type 分组，frequency 在每条 item 内；同标的不同频次各一条。
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
    # 期货（日盘 + 夜盘）
    'futures_minute': {
        'type': 'cron',
        'kwargs': {'hour': '9-14,21-23,0-2', 'minute': '*/5', 'day_of_week': 'mon-fri'},
    },
    'futures_daily': {
        'type': 'cron',
        'kwargs': {'hour': 15, 'minute': 30, 'day_of_week': 'mon-fri'},
    },
    'futures_weekly': {
        'type': 'cron',
        'kwargs': {'day_of_week': 'sat', 'hour': 8, 'minute': 0},
    },
    # X 简报 producer 自己从 SOCIAL_CONFIG['cron_hours'] 构造触发器；
    # 此处置 None 让 build_trigger 不注入，由 producer fallback。
    'x_briefing': None,
    # 行情早报：每天 09:31（A 股开盘后 1 分钟）一次
    'market_briefing': {
        'type': 'cron',
        'kwargs': {'hour': 9, 'minute': 31},
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

# 消息总线 backend：'memory'（进程内，默认）或 'redis'（跨进程，需 redis-server 可用）
MQ_BACKEND = 'memory'