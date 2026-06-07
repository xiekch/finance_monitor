import os
from dotenv import load_dotenv

load_dotenv()

PROXY = False
PROXY_URL = "http://127.0.0.1:7897"
if PROXY:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
else:
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

# 数据库配置
DATABASE_CONFIG = {
    'path': 'market_data.db',
    'backup_interval_hours': 24
}

WECHAT_MP_CONFIG = {
    'app_id': os.getenv('WECHAT_MP_APP_ID', ''),
    'app_secret': os.getenv('WECHAT_MP_APP_SECRET', ''),
    'thumb_media_id': os.getenv('WECHAT_MP_THUMB_MEDIA_ID', ''),
}

REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', 'localhost'),
    'port': int(os.getenv('REDIS_PORT', 6379)),
    'db': int(os.getenv('REDIS_DB', 0)),
    'password': os.getenv('REDIS_PASSWORD') or None,
    'decode_responses': True
}
