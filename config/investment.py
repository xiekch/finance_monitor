"""投资建议与复盘的配置。设计见 docs/plans/2026-10-26-investment-advice-design.md。"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADVICE_ROOT = REPO_ROOT / "advice"
ADVICE_REPO_URL = "https://github.com/xiekch/finance_monitor"
ADVICE_REPO_REF = "main"
MAX_ADVICE = 3
LESSON_LIMIT = 30
MAX_HORIZON_DAYS = 31
MAX_REFERENCE_AGE_DAYS = 3
MAX_REVIEWS_PER_RUN = 20
DISCLAIMER = "模型生成，非投资建议"
