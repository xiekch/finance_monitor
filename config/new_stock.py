"""新股上市提醒配置。"""

import os
from dotenv import load_dotenv

load_dotenv()

# 新股上市专用企微 webhook（可选，逗号分隔）；未配置时用默认 webhook
NEW_STOCK_WEBHOOK_URLS: list[str] = [
    u.strip() for u in os.getenv("NEW_STOCK_WEBHOOK_URL", "").split(",") if u.strip()
]
