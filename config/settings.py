import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录；运行时产物（DB / 日志）统一放这两个目录下
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

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
    'path': str(DATA_DIR / 'market_data.db'),
    'backup_interval_hours': 24
}

# 日志配置
LOG_FILE = str(LOG_DIR / 'app.log')
